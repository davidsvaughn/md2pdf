import os
import shutil
import subprocess
import sys
import json
import base64
from pathlib import Path
from typing import List, Dict, Any
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

    def pdf_to_images(self) -> List[str]:
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
                if action["original"] not in content:
                    print(f"WARNING: Could not find text to replace in {target_path}")
                    continue
                content = content.replace(action["original"], action["replacement"])
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
