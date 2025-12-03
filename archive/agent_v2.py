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

try:
    from openai import OpenAI
    from pdf2image import convert_from_path
except ImportError:
    print("Please install dependencies: pip install openai pdf2image")
    sys.exit(1)

MODEL = os.environ.get("MODEL", "gpt-5.1")
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", 5))
SYSTEM_PROMPT = "p5.md"  # file under prompts/


class ReportAgent:
    """
    Agent that:
      - Renders Markdown+CSS to PDF
      - Converts PDF pages to images
      - Lets a vision-capable model inspect the result
      - Uses proper OpenAI tools to read/edit files and rollback
      - Iterates until the model says the report passes
    """

    def __init__(self, markdown_path: str, pdf_path: str, css_path: str, api_key: str = None):
        self.markdown_path = Path(markdown_path)
        self.pdf_path = Path(pdf_path)
        self.css_path = Path(css_path)

        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self.max_iterations = MAX_ITERATIONS

        # history for rollback
        self.history: List[Dict[str, Any]] = []
        # full chat history (excluding system) across iterations
        self.chat_history: List[Dict[str, Any]] = []

        # initial snapshot
        self.save_snapshot()

        # tool registry
        self.tools = self._build_tools_schema()
        self.tool_funcs = {
            "list_dir": self.tool_list_dir,
            "read_file": self.tool_read_file,
            "search_text": self.tool_search_text,
            "replace_in_file": self.tool_replace_in_file,
            "append_to_file": self.tool_append_to_file,
            "insert_after": self.tool_insert_after,
            "apply_patch": self.tool_apply_patch,
            "rollback": self.tool_rollback,
        }

    # -------------------------------------------------------------------------
    # Snapshots / rollback
    # -------------------------------------------------------------------------

    def save_snapshot(self) -> int:
        """Save current file states for potential rollback. Returns snapshot index."""
        snapshot = {
            "markdown": self.markdown_path.read_text(),
            "css": self.css_path.read_text(),
            "index": len(self.history),
        }
        self.history.append(snapshot)
        print(f"Saved snapshot #{snapshot['index']}")
        return snapshot["index"]

    def rollback_internal(self, steps: int = 1) -> bool:
        """Rollback to a previous state. Returns True if successful."""
        target_index = len(self.history) - steps - 1
        if target_index < 0:
            print(f"Cannot rollback {steps} step(s) - only {len(self.history)} snapshot(s) available")
            return False

        snapshot = self.history[target_index]
        self.markdown_path.write_text(snapshot["markdown"])
        self.css_path.write_text(snapshot["css"])

        # Trim history to the rollback point
        self.history = self.history[: target_index + 1]
        print(f"Rolled back to snapshot #{snapshot['index']}")
        return True

    # -------------------------------------------------------------------------
    # PDF generation / vision support
    # -------------------------------------------------------------------------

    def run_generator(self):
        """Runs the existing md2pdf.py script."""
        print(f"Generating PDF: {self.pdf_path}...")
        cmd = [
            sys.executable,
            "md2pdf.py",
            str(self.markdown_path),
            str(self.pdf_path),
            "--css",
            str(self.css_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Generation failed: {result.stderr}")

    def pdf_to_images(self) -> List[str]:
        """
        Converts PDF pages to base64 encoded JPEG images.
        Returns: list of base64 strings (without data: prefix).
        """
        print("Converting PDF to images for inspection...")
        images = convert_from_path(str(self.pdf_path))
        base64_images: List[str] = []

        import io

        for img in images:
            img.thumbnail((1024, 1024))
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            img_str = base64.b64encode(buf.getvalue()).decode("utf-8")
            base64_images.append(img_str)

        return base64_images

    # -------------------------------------------------------------------------
    # Tools: schema
    # -------------------------------------------------------------------------

    def _build_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Define tools in OpenAI function-calling schema.
        All mutating tools implicitly save a snapshot before changing files.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "description": "List directory entries with optional glob filter.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory path to list."},
                            "glob": {
                                "type": "string",
                                "description": "Glob pattern, e.g. '*.md' or '*'.",
                                "default": "*",
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a slice of a text file for inspection.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to read."},
                            "start_line": {
                                "type": "integer",
                                "description": "1-based start line.",
                                "default": 1,
                            },
                            "end_line": {
                                "type": "integer",
                                "description": "1-based end line (inclusive).",
                                "default": 200,
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_text",
                    "description": "Search text in files using ripgrep for fast contextual lookup.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "root": {
                                "type": "string",
                                "description": "Root directory to search from.",
                                "default": ".",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum matches.",
                                "default": 20,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "replace_in_file",
                    "description": "Replace exact text in a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "original": {"type": "string"},
                            "replacement": {"type": "string"},
                        },
                        "required": ["path", "original", "replacement"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "append_to_file",
                    "description": "Append content at the end of a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "insert_after",
                    "description": "Insert content after a marker string in a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "marker": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "marker", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "apply_patch",
                    "description": "Apply a unified diff patch to a file (patch -u).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "patch": {"type": "string"},
                        },
                        "required": ["path", "patch"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rollback",
                    "description": "Rollback to a previous snapshot of Markdown/CSS.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "steps": {
                                "type": "integer",
                                "description": "How many steps back to go (>=1).",
                                "default": 1,
                            }
                        },
                        "required": [],
                    },
                },
            },
        ]

    # -------------------------------------------------------------------------
    # Tools: implementations
    # -------------------------------------------------------------------------

    def tool_list_dir(self, path: str, glob: str = "*") -> Dict[str, Any]:
        target = Path(path)
        if not target.exists():
            return {"ok": False, "error": f"Path does not exist: {path}"}
        if not target.is_dir():
            return {"ok": False, "error": f"Path is not a directory: {path}"}
        entries = []
        for entry in sorted(target.glob(glob)):
            entries.append(
                {
                    "name": entry.name,
                    "path": str(entry),
                    "type": "dir" if entry.is_dir() else "file",
                }
            )
        return {"ok": True, "entries": entries}

    def tool_read_file(self, path: str, start_line: int = 1, end_line: int = 200) -> Dict[str, Any]:
        target = Path(path)
        if not target.exists():
            return {"ok": False, "error": f"File does not exist: {path}"}
        if target.stat().st_size > 500_000:
            return {"ok": False, "error": f"File too large to read safely: {target.stat().st_size} bytes"}
        lines = target.read_text().splitlines()
        start = max(start_line - 1, 0)
        end = min(end_line, len(lines))
        snippet = "\n".join(lines[start:end])
        return {
            "ok": True,
            "path": str(target),
            "start_line": start_line,
            "end_line": end_line,
            "content": snippet,
        }

    def tool_search_text(self, query: str, root: str = ".", max_results: int = 20) -> Dict[str, Any]:
        cmd = [
            "rg",
            "--line-number",
            "--no-heading",
            "--context",
            "1",
            "-m",
            str(max_results),
            query,
            root,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode not in (0, 1):  # 1 means no matches
            return {"ok": False, "error": result.stderr.strip() or "Unknown ripgrep error"}
        return {"ok": True, "matches": result.stdout.strip()}

    # All mutating tools save a snapshot before changing anything.

    def tool_replace_in_file(self, path: str, original: str, replacement: str) -> Dict[str, Any]:
        self.save_snapshot()
        target = Path(path)
        if not target.exists():
            return {"ok": False, "error": f"File does not exist: {path}"}
        content = target.read_text()
        if original not in content:
            return {"ok": False, "error": "Original text not found, no replacement made."}
        content = content.replace(original, replacement)
        target.write_text(content)
        return {"ok": True, "message": "Replacement applied."}

    def tool_append_to_file(self, path: str, content: str) -> Dict[str, Any]:
        self.save_snapshot()
        target = Path(path)
        if not target.exists():
            return {"ok": False, "error": f"File does not exist: {path}"}
        existing = target.read_text()
        target.write_text(existing + "\n" + content)
        return {"ok": True, "message": "Content appended."}

    def tool_insert_after(self, path: str, marker: str, content: str) -> Dict[str, Any]:
        self.save_snapshot()
        target = Path(path)
        if not target.exists():
            return {"ok": False, "error": f"File does not exist: {path}"}
        text = target.read_text()
        idx = text.find(marker)
        if idx == -1:
            return {"ok": False, "error": "Marker not found."}
        insert_pos = idx + len(marker)
        prefix = text[:insert_pos]
        suffix = text[insert_pos:]
        insertion = content
        if not prefix.endswith("\n"):
            insertion = "\n" + insertion
        new_text = prefix + insertion + suffix
        target.write_text(new_text)
        return {"ok": True, "message": "Content inserted after marker."}

    def tool_apply_patch(self, path: str, patch: str) -> Dict[str, Any]:
        self.save_snapshot()
        target = Path(path)
        if not target.exists():
            return {"ok": False, "error": f"File does not exist: {path}"}
        result = subprocess.run(
            ["patch", "-u", str(target)],
            input=patch,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip() or "Patch failed."}
        return {"ok": True, "message": "Patch applied."}

    def tool_rollback(self, steps: int = 1) -> Dict[str, Any]:
        if steps < 1:
            return {"ok": False, "error": "Steps must be >= 1"}
        success = self.rollback_internal(steps=steps)
        return {"ok": success, "message": "Rolled back." if success else "Rollback failed."}

    # -------------------------------------------------------------------------
    # Agent loop using proper tools
    # -------------------------------------------------------------------------

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / SYSTEM_PROMPT
        return prompt_path.read_text()

    def run_agent_iteration(self, iteration: int, images_b64: List[str]) -> bool:
        """
        Single iteration:
          - send current Markdown+CSS and rendered PDF images
          - allow model to call tools
          - expect final assistant message to contain either:
              - 'STATUS: PASS' -> return True
              - otherwise -> return False and allow outer loop to continue
        """
        any_tools_called = False  # Track if model called any tools this iteration
        system_prompt = self._load_system_prompt()
        md_content = self.markdown_path.read_text()
        css_content = self.css_path.read_text()

        # Vision-capable user content: text + images
        user_content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"Iteration {iteration}.\n\n"
                    "Here is the current Markdown and CSS:\n\n"
                    "Markdown:\n```markdown\n"
                    f"{md_content}\n"
                    "```\n\n"
                    "CSS:\n```css\n"
                    f"{css_content}\n"
                    "```\n\n"
                    "Now inspect the rendered PDF pages below. "
                    "Use tools to read/edit files as needed. "
                    "When you believe the report is acceptable, respond with 'STATUS: PASS' "
                    "in your final message. If more fixes are needed, respond with "
                    "'STATUS: CONTINUE' and explain what you changed and why."
                ),
            }
        ]

        for img_b64 in images_b64:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                }
            )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *self.chat_history,
            {"role": "user", "content": user_content},
        ]

        while True:
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": msg.tool_calls,
                }
            )

            tool_calls = msg.tool_calls or []
            if tool_calls:
                any_tools_called = True  # Mark that tools were used
                # Execute each tool call and append tool results
                for tool_call in tool_calls:
                    name = tool_call.function.name
                    raw_args = tool_call.function.arguments or "{}"
                    print(f"  Tool call: {name}({raw_args[:100]}...)" if len(raw_args) > 100 else f"  Tool call: {name}({raw_args})")
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                    func = self.tool_funcs.get(name)
                    if func is None:
                        result = {"ok": False, "error": f"Unknown tool: {name}"}
                    else:
                        result = func(**args)

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": json.dumps(result),
                        }
                    )
                # Loop again so the model can see tool results
                continue

            # No tool calls: this is the model's final answer for this iteration
            final_content = msg.content or ""
            self.chat_history.append({"role": "assistant", "content": final_content})

            # Debug: show model response
            print(f"\n--- Model Response (iteration {iteration}) ---")
            print(final_content[:1000] + ("..." if len(final_content) > 1000 else ""))
            print("--- End Response ---\n")

            lowered = final_content.lower()
            if "status: pass" in lowered:
                # Enforce: on iteration 1, model must call tools before passing
                if iteration == 1 and not any_tools_called:
                    print("⚠️  Model tried to PASS on iteration 1 without calling any tools!")
                    print("    Rejecting PASS - forcing another iteration.")
                    # Add a nudge message to chat history
                    self.chat_history.append({
                        "role": "user",
                        "content": (
                            "You declared PASS without using any tools to verify or fix issues. "
                            "Please carefully re-examine the PDF images. Look specifically for:\n"
                            "1) Lists rendering INLINE instead of vertically stacked with bullets\n"
                            "2) Page economy issues (sparse final page)\n"
                            "If you find issues, use replace_in_file to fix them. "
                            "Only declare STATUS: PASS after thorough verification."
                        )
                    })
                    return False
                print("Model signaled STATUS: PASS")
                return True
            else:
                print("Model did not signal pass; continuing.")
                return False

    def run(self):
        for i in range(self.max_iterations):
            print(f"\n--- Iteration {i + 1} ---")

            # 1. Generate PDF from current sources
            self.run_generator()

            # 2. Convert PDF to images for visual inspection
            images_b64 = self.pdf_to_images()

            # 3. Let the model inspect, call tools, and decide whether we're done
            done = self.run_agent_iteration(iteration=i + 1, images_b64=images_b64)
            if done:
                break
        else:
            print("Max iterations reached without STATUS: PASS.")

        print(f"\nHistory: {len(self.history)} snapshot(s) saved for potential rollback")


if __name__ == "__main__":
    # Example usage

    base = "premium"  # or "basic"

    shutil.copyfile(f"docs/x1-{base}.md", f"x1-{base}.md")
    shutil.copyfile("docs/custom.css", "css/custom.css")

    agent = ReportAgent(
        markdown_path=f"x1-{base}.md",
        pdf_path=f"x1-{base}.pdf",
        css_path="css/custom.css",
    )
    agent.run()
