#!/usr/bin/env python3
"""
Pipeline: JSON -> flattened Markdown -> force line breaks -> PDF.

Steps:
1) Flatten JSON using the same logic as flatten_json_to_md.py
2) Add trailing spaces to force line breaks (simple approach)
3) Render to PDF via md2pdf.py with css/custom.css by default
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from flatten_json_to_md import flatten, to_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Flatten a JSON file, force line breaks, and render to PDF."
    )
    parser.add_argument(
        "input_json",
        nargs="?",
        default="docs/research_ArtCentrica.json",
        help="Path to the input JSON file (default: docs/research_ArtCentrica.json).",
    )
    parser.add_argument(
        "-o",
        "--output-md",
        type=Path,
        help="Output Markdown path (defaults to input JSON with .md extension).",
    )
    parser.add_argument(
        "-p",
        "--output-pdf",
        type=Path,
        help="Output PDF path (defaults to input JSON with .pdf extension).",
    )
    parser.add_argument(
        "--css",
        type=Path,
        default=Path("css/custom.css"),
        help="CSS file to use for PDF rendering (default: css/custom.css).",
    )
    parser.add_argument(
        "--separator",
        default=".",
        help="Separator for nested object keys (default: '.').",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Encoding for reading/writing files (default: utf-8).",
    )
    parser.add_argument(
        "--no-mathjax",
        action="store_true",
        help="Disable MathJax when calling md2pdf.py (faster if not needed).",
    )
    return parser.parse_args()


def _is_code_fence(line: str) -> bool:
    """Check if line is a code fence marker."""
    stripped = line.lstrip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def add_trailing_spaces(markdown: str) -> str:
    """
    Add two trailing spaces to the end of every line to force line breaks.
    Skips lines inside code blocks to preserve code formatting.
    """
    lines = markdown.splitlines()
    result = []
    in_code_block = False
    
    for line in lines:
        # Track code block state
        if _is_code_fence(line):
            in_code_block = not in_code_block
            result.append(line)
            continue
        
        # Don't modify lines inside code blocks
        if in_code_block:
            result.append(line)
            continue
        
        # Don't add spaces to blank lines
        if not line.strip():
            result.append(line)
            continue
        
        # Add trailing spaces if not already present
        if line.rstrip().endswith("  "):
            result.append(line)
        else:
            result.append(line.rstrip() + "  ")
    
    return "\n".join(result)


def generate_pdf(markdown: Path, pdf_path: Path, css_path: Path, *, no_mathjax: bool) -> None:
    """Generate PDF from markdown using md2pdf.py."""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "md2pdf.py"),
        str(markdown),
        str(pdf_path),
        "--css",
        str(css_path),
    ]
    if no_mathjax:
        cmd.append("--no-mathjax")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"md2pdf.py failed:\n{result.stderr.strip()}")


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_json)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    output_md = args.output_md or input_path.with_suffix(".md")
    output_pdf = args.output_pdf or input_path.with_suffix(".pdf")

    # Step 1: Flatten JSON to markdown
    with input_path.open("r", encoding=args.encoding) as handle:
        data: Any = json.load(handle)

    flattened = flatten(data, sep=args.separator)
    markdown = to_markdown(flattened)
    print(f"[flatten] generated {len(flattened)} sections")

    # Step 2: Add trailing spaces to force line breaks
    markdown = add_trailing_spaces(markdown)
    
    # Write markdown
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(markdown, encoding=args.encoding)
    print(f"[markdown] wrote to {output_md}")

    # Step 3: Generate PDF
    generate_pdf(output_md, output_pdf, args.css, no_mathjax=args.no_mathjax)
    print(f"[pdf] wrote to {output_pdf.resolve()}")


if __name__ == "__main__":
    main()
