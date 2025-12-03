import os
import re
import shutil
import subprocess
import sys
import json
import base64
from rapidfuzz.fuzz import ratio
from pathlib import Path
from typing import List, Dict, Any, Tuple
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
    

MODEL = os.environ.get("MODEL", "gpt-5.1")
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", 5))
SYSTEM_PROMPT = "p4.md"


def best_fuzzy_span(text: str, query: str, *, threshold=95, win=1, max_window_factor=1.01):
    """
    Find the best fuzzy match span inside `text` that approximates `query`.
    """

    qlen = len(query)
    best_score = -1
    best_span = None

    # Search for windows of length roughly [0.5q, 2q]
    # min_w = max(1, int(qlen / max_window_factor))
    # max_w = min(len(text), int(qlen * max_window_factor))
    
    min_w = qlen-win
    max_w = qlen+win

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
    agent.run()
