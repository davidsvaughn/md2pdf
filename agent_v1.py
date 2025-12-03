import os
import re
import shutil
import subprocess
import sys
import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()

# You would need to install these:
# pip install openai pdf2image
try:
    from openai import OpenAI
    from pdf2image import convert_from_path
except ImportError:
    print("Please install dependencies: pip install openai pdf2image")
    sys.exit(1)
    
# MODEL = "gpt-4o"  # Replace with a vision-capable model if available
MODEL = os.environ.get("MODEL", "gpt-5.1") # "gpt-4o"
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", 5))
SYSTEM_PROMPT = "p4.md"


from rapidfuzz.fuzz import ratio
from rapidfuzz import process

def best_fuzzy_span(text: str, query: str, *, threshold=95, max_window_factor=1.01):
    """
    Find the best fuzzy match span inside `text` that approximates `query`.
    Allows window sizes up to max_window_factor * len(query).
    """

    qlen = len(query)
    best_score = -1
    best_span = None

    # Search for windows of length roughly [0.5q, 2q]
    min_w = max(1, int(qlen / max_window_factor))
    max_w = min(len(text), int(qlen * max_window_factor))

    for w in range(min_w, max_w + 1):
        for start in range(0, len(text) - w + 1):
            chunk = text[start:start + w]
            s = ratio(chunk, query)
            if s > best_score:
                best_score = s
                best_span = (start, start + w)

    if best_score < threshold:
        return None

    return best_span, best_score


def fuzzy_find_replace(text, original, replacement, threshold=80):
    result = best_fuzzy_span(text, original, threshold=threshold)
    if not result:
        return text, False

    (start, end), score = result
    
    print(f"INFO: Fuzzy match found with score {score:.1f}%")

    new_text = text[:start] + replacement + text[end:]
    return new_text, True


def flexible_find_replace(content: str, original: str, replacement: str) -> Tuple[str, bool]:
    """
    Find/replace that handles:
    Returns: (new_content, success_bool)
    """
    # First try exact match (fastest)
    if original in content:
        return content.replace(original, replacement, 1), True
    
    # Next try fuzzy match
    new_content, success = fuzzy_find_replace(content, original, replacement, threshold=85)
    if success:
        return new_content, True
    
    # If exact match fails, try flexible whitespace matching
    # Escape all regex special chars
    escaped = re.escape(original)
    
    # Convert escaped whitespace sequences to flexible patterns
    # re.escape turns \n into \\n and space into '\ '
    # We want to match any whitespace sequence flexibly
    pattern = re.sub(r'(\\\n|\\ )+', r'\\s+', escaped)
    
    try:
        new_content, count = re.subn(pattern, replacement, content, count=1)
        if count > 0:
            return new_content, True
    except re.error as e:
        print(f"WARNING: Regex error: {e}")
        
    print(f"WARNING: Could not find\n{original!r}")
    
    return content, False


class ReportAgent:
    def __init__(self, markdown_path: str, pdf_path: str, css_path: str, api_key: str = None):
        self.markdown_path = Path(markdown_path)
        self.pdf_path = Path(pdf_path)
        self.css_path = Path(css_path)
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self.max_iterations = MAX_ITERATIONS
        self.history = []

    def save_snapshot(self) -> int:
        """Save current file states for potential rollback. Returns snapshot index."""
        snapshot = {
            "markdown": self.markdown_path.read_text(),
            "css": self.css_path.read_text(),
            "index": len(self.history)
        }
        self.history.append(snapshot)
        print(f"Saved snapshot #{snapshot['index']}")
        return snapshot["index"]

    def rollback(self, steps: int = 1) -> bool:
        """Rollback to a previous state. Returns True if successful."""
        target_index = len(self.history) - steps - 1
        if target_index < 0:
            print(f"Cannot rollback {steps} step(s) - only {len(self.history)} snapshot(s) available")
            return False
        
        snapshot = self.history[target_index]
        self.markdown_path.write_text(snapshot["markdown"])
        self.css_path.write_text(snapshot["css"])
        
        # Trim history to the rollback point
        self.history = self.history[:target_index + 1]
        print(f"Rolled back to snapshot #{snapshot['index']}")
        return True

    def run_generator(self):
        """Runs the existing md2pdf.py script."""
        print(f"Generating PDF: {self.pdf_path}...")
        cmd = [
            sys.executable, "md2pdf.py",
            str(self.markdown_path),
            str(self.pdf_path),
            "--css", str(self.css_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Generation failed: {result.stderr}")

    def pdf_to_images(self, debug=False) -> List[str]:
        """Converts PDF pages to base64 encoded JPEG images."""
        print("Converting PDF to images for inspection...")
        # Requires poppler-utils installed on the system
        images = convert_from_path(str(self.pdf_path))
        base64_images = []
        
        for img in images:
            # Resize to reduce token cost while maintaining readability
            img.thumbnail((1024, 1024))
            
            # Save to buffer
            import io
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            img_str = base64.b64encode(buf.getvalue()).decode("utf-8")
            base64_images.append(img_str)
            
            # if debug, also save to disk for local viewing
            if debug:
                idx = len(base64_images)
                debug_path = self.pdf_path.parent / f"debug_page_{idx}.jpg"
                img.save(debug_path, format="JPEG")
                print(f"Saved debug image: {debug_path}")
            
        return base64_images

    def evaluate_and_plan(self, images: List[str], iteration: int) -> Dict[str, Any]:
        """Asks the VLM to evaluate the report and suggest changes."""
        print("Consulting the design agent...")
        
        # Read current file contents to give context
        md_content = self.markdown_path.read_text()
        css_content = self.css_path.read_text()

        # Load system prompt from file
        prompt_path = Path(__file__).parent / "prompts" / SYSTEM_PROMPT
        system_prompt = prompt_path.read_text()

        user_content = [
            {"type": "text", "text": f"**Iteration: {iteration}**\n\nHere are the current files:\n\nMarkdown:\n```\n{md_content}\n```\n\nCSS:\n```\n{css_content}\n```"},
            {"type": "text", "text": "Here are the rendered PDF pages:"}
        ]
        
        for img_b64 in images:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        response = self.client.chat.completions.create(
            model=MODEL, # Or a similar vision-capable model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"}
        )
        
        return json.loads(response.choices[0].message.content)

    def _evaluate_chunk(
        self,
        chunk_images: List[str],
        page_start: int,
        page_end: int,
        total_pages: int,
        iteration: int,
        md_content: str,
        css_content: str,
        system_prompt: str
    ) -> Dict[str, Any]:
        """
        Evaluate a chunk of PDF pages in a single LLM call.
        
        Args:
            chunk_images: List of base64-encoded images for this chunk
            page_start: 1-based starting page number
            page_end: 1-based ending page number (inclusive)
            total_pages: Total number of pages in the full document
            iteration: Current iteration number
            md_content: Full Markdown content
            css_content: Full CSS content
            system_prompt: System prompt text
            
        Returns:
            JSON response from the LLM with status, critique, and actions
        """
        # Build page context string
        if page_start == page_end:
            page_context = f"page {page_start} of {total_pages}"
        else:
            page_context = f"pages {page_start}-{page_end} of {total_pages}"
        
        user_content = [
            {
                "type": "text", 
                "text": (
                    f"**Iteration: {iteration}**\n\n"
                    f"**You are analyzing {page_context} total pages.**\n\n"
                    f"Here are the current files:\n\n"
                    f"Markdown:\n```\n{md_content}\n```\n\n"
                    f"CSS:\n```\n{css_content}\n```"
                )
            },
            {
                "type": "text", 
                "text": f"Here are the rendered PDF pages ({page_context}):"
            }
        ]
        
        # Add images with page number labels
        for i, img_b64 in enumerate(chunk_images):
            page_num = page_start + i
            user_content.append({
                "type": "text",
                "text": f"**Page {page_num}:**"
            })
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        response = self.client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        # Tag the result with page range for later merging
        result["_page_range"] = (page_start, page_end)
        return result

    def evaluate_and_plan_parallel(
        self,
        images: List[str],
        iteration: int,
        num_bins: Optional[int] = None,
        per_image: bool = False,
        max_workers: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Parallel version of evaluate_and_plan that splits images into chunks
        and processes them concurrently.
        
        Args:
            images: List of base64-encoded PDF page images
            iteration: Current iteration number
            num_bins: Number of bins to split images into (default: 2)
            per_image: If True, each image gets its own LLM call (overrides num_bins)
            max_workers: Maximum number of parallel workers (default: num_bins)
            
        Returns:
            Combined JSON response with status, critique, and merged actions
        """
        print("Consulting the design agent (parallel mode)...")
        
        total_pages = len(images)
        
        # Determine number of bins
        if per_image:
            num_bins = total_pages
        elif num_bins is None:
            num_bins = min(2, total_pages)  # Default to 2 bins, but not more than total pages
        else:
            num_bins = min(num_bins, total_pages)  # Can't have more bins than pages
        
        if max_workers is None:
            max_workers = num_bins
        
        # Read current file contents (shared across all chunks)
        md_content = self.markdown_path.read_text()
        css_content = self.css_path.read_text()
        
        # Load system prompt
        prompt_path = Path(__file__).parent / "prompts" / SYSTEM_PROMPT
        system_prompt = prompt_path.read_text()
        
        # Split images into roughly equal bins
        chunks = []
        base_size = total_pages // num_bins
        remainder = total_pages % num_bins
        
        start_idx = 0
        for i in range(num_bins):
            # Distribute remainder across first bins
            chunk_size = base_size + (1 if i < remainder else 0)
            end_idx = start_idx + chunk_size
            
            chunk_images = images[start_idx:end_idx]
            page_start = start_idx + 1  # 1-based page numbers
            page_end = end_idx  # 1-based, inclusive
            
            chunks.append((chunk_images, page_start, page_end))
            start_idx = end_idx
        
        print(f"  Splitting {total_pages} pages into {num_bins} chunk(s): {[f'p{c[1]}-{c[2]}' for c in chunks]}")
        
        # Execute chunks in parallel
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._evaluate_chunk,
                    chunk_images,
                    page_start,
                    page_end,
                    total_pages,
                    iteration,
                    md_content,
                    css_content,
                    system_prompt
                ): (page_start, page_end)
                for chunk_images, page_start, page_end in chunks
            }
            
            for future in as_completed(futures):
                page_range = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    print(f"  Completed chunk pages {page_range[0]}-{page_range[1]}: status={result.get('status')}")
                except Exception as e:
                    print(f"  ERROR in chunk pages {page_range[0]}-{page_range[1]}: {e}")
                    # Create a failure result for this chunk
                    results.append({
                        "status": "fail",
                        "critique": f"Error processing pages {page_range[0]}-{page_range[1]}: {str(e)}",
                        "actions": [],
                        "_page_range": page_range
                    })
        
        # Sort results by page range for consistent ordering
        results.sort(key=lambda r: r.get("_page_range", (0, 0))[0])
        
        # Combine results
        return self._combine_parallel_results(results)

    def _combine_parallel_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Combine results from multiple parallel chunk evaluations.
        
        Args:
            results: List of JSON responses from parallel chunk evaluations
            
        Returns:
            Combined JSON response with:
            - status: "pass" only if ALL chunks passed
            - critique: Combined critiques with page range prefixes
            - actions: Merged action lists in page order
        """
        all_passed = all(r.get("status") == "pass" for r in results)
        
        if all_passed:
            return {"status": "pass"}
        
        # Combine critiques
        critiques = []
        all_actions = []
        
        for result in results:
            page_range = result.get("_page_range", (0, 0))
            status = result.get("status", "unknown")
            
            if status != "pass":
                critique = result.get("critique", "")
                if critique:
                    if page_range[0] == page_range[1]:
                        prefix = f"[Page {page_range[0]}]"
                    else:
                        prefix = f"[Pages {page_range[0]}-{page_range[1]}]"
                    critiques.append(f"{prefix} {critique}")
                
                # Collect actions
                actions = result.get("actions", [])
                all_actions.extend(actions)
        
        combined_critique = "\n\n".join(critiques) if critiques else "Issues found but no specific critique provided."
        
        return {
            "status": "fail",
            "critique": combined_critique,
            "actions": all_actions
        }

    def apply_changes(self, actions: List[Dict[str, Any]]) -> bool:
        """Applies the suggested changes to files. Returns True if any changes were made."""
        changes_made = False
        
        for action in actions:
            # Handle rollback action
            if action.get("type") == "rollback":
                steps = action.get("steps", 1)
                print(f"Rollback requested: {steps} step(s)")
                return self.rollback(steps)
            
            target_path = self.markdown_path if action["file"] == "markdown" else self.css_path
            content = target_path.read_text()
            
            if action["type"] == "replace_in_file":
                # Use flexible find/replace that handles whitespace variations and regex chars
                new_content, success = flexible_find_replace(
                    content, 
                    action["original"], 
                    action["replacement"]
                )
                if not success:
                    print(f"WARNING: Could not find text to replace in {target_path}")
                    print(f"  Original (first 100 chars): {action['original'][:100]!r}")
                    continue
                content = new_content
                print(f"Applied replacement in {target_path}")
                changes_made = True
                
            elif action["type"] == "append_to_file":
                content += "\n" + action["content"]
                print(f"Appended content to {target_path}")
                changes_made = True
            
            target_path.write_text(content)
        
        return changes_made

    def run(self):
        # Save initial state before any modifications
        self.save_snapshot()
        
        for i in range(self.max_iterations):
            print(f"\n--- Iteration {i+1} ---")
            
            # 1. Generate
            self.run_generator()
            
            # 2. See
            images = self.pdf_to_images()
            
            # 3. Think
            plan = self.evaluate_and_plan(images, iteration=i+1)
            
            if plan["status"] == "pass":
                print("Report looks good! Process complete.")
                break
            
            print(f"Critique: {plan.get('critique')}")
            
            # 4. Act
            if "actions" in plan:
                # Save snapshot before applying changes (for potential rollback)
                self.save_snapshot()
                self.apply_changes(plan["actions"])
            else:
                print("No actions suggested despite failure.")
                break
        else:
            print("Max iterations reached without passing.")
        
        print(f"\nHistory: {len(self.history)} snapshot(s) saved for potential rollback")

    def run_parallel(self, num_bins: Optional[int] = None, per_image: bool = False):
        """
        Same as run() but uses parallel evaluation for speedup.
        
        Args:
            num_bins: Number of bins to split pages into (default: 2)
            per_image: If True, each page gets its own LLM call
        """
        # Save initial state before any modifications
        self.save_snapshot()
        
        for i in range(self.max_iterations):
            print(f"\n--- Iteration {i+1} ---")
            
            # 1. Generate
            self.run_generator()
            
            # 2. See
            images = self.pdf_to_images()
            
            # 3. Think (parallel)
            plan = self.evaluate_and_plan_parallel(
                images, 
                iteration=i+1,
                num_bins=num_bins,
                per_image=per_image
            )
            
            if plan["status"] == "pass":
                print("Report looks good! Process complete.")
                break
            
            print(f"Critique: {plan.get('critique')}")
            
            # 4. Act
            if "actions" in plan:
                # Save snapshot before applying changes (for potential rollback)
                self.save_snapshot()
                self.apply_changes(plan["actions"])
            else:
                print("No actions suggested despite failure.")
                break
        else:
            print("Max iterations reached without passing.")
        
        print(f"\nHistory: {len(self.history)} snapshot(s) saved for potential rollback")


if __name__ == "__main__":
    # Example usage
    
    # reset files for demo
    # base = "basic"
    base = "premium"
    
    shutil.copyfile(f"docs/x1-{base}.md", f"x1-{base}.md")
    shutil.copyfile("docs/custom.css", "css/custom.css")
    
    agent = ReportAgent(
        markdown_path=f"x1-{base}.md",
        pdf_path=f"x1-{base}.pdf",
        css_path="css/custom.css"
    )
    
    # original run
    # agent.run()
    
    # Split into 3 parallel chunks
    # agent.run_parallel(num_bins=3)

    # Or one LLM call per page
    agent.run_parallel(per_image=True)
