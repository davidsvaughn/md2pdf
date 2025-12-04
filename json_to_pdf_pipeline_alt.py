#!/usr/bin/env python3
"""
Pipeline: JSON -> flattened Markdown -> auto-fix broken lists -> PDF.

Steps:
1) Flatten JSON using the same logic as flatten_json_to_md.py
2) Auto-fix broken bullet lists by inserting blank lines (logic adapted from sdk-agent/adk-agent)
3) Render to PDF via md2pdf.py with css/custom.css by default
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pdfplumber

from flatten_json_to_md import flatten, to_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Flatten a JSON file, fix broken markdown lists, and render to PDF."
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
        "--max-iterations",
        type=int,
        default=1,
        help="Maximum passes to fix broken lists (default: 1).",
    )
    parser.add_argument(
        "--no-mathjax",
        action="store_true",
        help="Disable MathJax when calling md2pdf.py (faster if not needed).",
    )
    return parser.parse_args()


# ----------------------------
# Markdown list helpers
# ----------------------------

def _is_bullet_line(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("-", "*", "+")) and len(stripped) > 1 and stripped[1].isspace()


def _get_bullet_text(line: str) -> str:
    stripped = line.lstrip()
    return stripped[1:].lstrip() if stripped and stripped[0] in "-*+" else stripped


def _first_two_lines_of_bulleted_lists(md: str) -> List[Tuple[str, str, str]]:
    lines = md.splitlines()
    n = len(lines)
    out: List[Tuple[str, str, str]] = []
    i = 0

    while i < n:
        if _is_bullet_line(lines[i]):
            prev_bullet = _is_bullet_line(lines[i - 1]) if i > 0 else False
            prev_blank = i == 0 or lines[i - 1].strip() == ""
            if not prev_bullet or prev_blank:
                first_line = lines[i]
                second_line = ""
                first_word_of_second = ""

                j = i + 1
                while j < n:
                    if _is_bullet_line(lines[j]):
                        second_line = lines[j]
                        words = second_line.split()
                        if words:
                            first_word_of_second = words[0].strip('*_"\'()')
                        break
                    elif lines[j].strip() == "" or lines[j].startswith(" "):
                        j += 1
                        continue
                    else:
                        break
                    j += 1

                if second_line and first_word_of_second:
                    out.append((first_line, second_line, first_word_of_second))

                while j < n and (_is_bullet_line(lines[j]) or lines[j].strip() == "" or lines[j].startswith(" ")):
                    j += 1
                i = j
                continue
        i += 1

    return out


def _first_lines_of_bulleted_lists(md: str) -> List[str]:
    lines = md.splitlines()
    n = len(lines)
    out: List[str] = []
    i = 0

    while i < n:
        if _is_bullet_line(lines[i]):
            prev_bullet = _is_bullet_line(lines[i - 1]) if i > 0 else False
            prev_blank = i == 0 or lines[i - 1].strip() == ""
            if not prev_bullet or prev_blank:
                out.append(lines[i])
                j = i + 1
                while j < n and (_is_bullet_line(lines[j]) or lines[j].strip() == "" or lines[j].startswith(" ")):
                    j += 1
                i = j
                continue
        i += 1
    return out


def _normalize(s: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9]", "", s)


def find_broken_lists(md_path: Path, pdf_path: Path) -> Dict:
    if not md_path.exists():
        return {"success": False, "error": f"Markdown not found: {md_path}"}
    if not pdf_path.exists():
        return {"success": False, "error": f"PDF not found: {pdf_path}"}

    md_content = md_path.read_text(encoding="utf-8")
    list_data = _first_two_lines_of_bulleted_lists(md_content)

    if not list_data:
        return {
            "success": True,
            "broken_lists": [],
            "correct_lists": [],
            "broken_count": 0,
            "total_count": 0,
            "message": "No bulleted lists found",
        }

    pdf_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pdf_text += page.extract_text() or ""
            pdf_text += "\n"

    pdf_lines = pdf_text.splitlines()
    broken_lists: List[str] = []
    correct_lists: List[str] = []
    
    n = 2
    for first_line, second_line, expected_word in list_data:
        first_text = _get_bullet_text(first_line).strip()
        second_text = _get_bullet_text(second_line).strip()
        first_words = _normalize(" ".join(first_text.split()[:2]))
        second_words = _normalize(" ".join(second_text.split()[:2]))
        
        if first_words.lower().startswith("companyfounding"):
            print(first_words, second_words)
            z=2

        list_is_vertical = False
        for i, pdf_line in enumerate(pdf_lines):
            pdf_line_norm = _normalize(pdf_line)
            
            if pdf_line_norm.lower().startswith("companyfounding"):
                print(pdf_line_norm)
                z=2
            
            if pdf_line_norm.startswith(first_words):
                # if second_words not in pdf_line_norm:
                for j in range(i + 1, min(i + 10, len(pdf_lines))):
                    if _normalize(pdf_lines[j]).startswith(second_words):
                        list_is_vertical = True
                        break
                # break

        if list_is_vertical:
            correct_lists.append(first_line.strip())
        else:
            broken_lists.append(first_line.strip())

    return {
        "success": True,
        "broken_lists": broken_lists,
        "correct_lists": correct_lists,
        "broken_count": len(broken_lists),
        "correct_count": len(correct_lists),
        "total_count": len(list_data),
    }


def fix_broken_list(md_path: Path, search_text: str) -> Dict:
    if not md_path.exists():
        return {"success": False, "error": f"Markdown not found: {md_path}"}

    content = md_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    search_lower = search_text.lower().strip()
    found_line = -1

    for i, line in enumerate(lines):
        if search_lower in line.lower():
            found_line = i
            break

    if found_line == -1:
        return {"success": False, "error": f'Text not found: "{search_text[:80]}"'}

    if found_line > 0 and lines[found_line - 1].strip() == "":
        return {"success": True, "already_exists": True, "line_number": found_line + 1}

    lines.insert(found_line, "\n")
    md_path.write_text("".join(lines), encoding="utf-8")
    return {"success": True, "line_number": found_line + 1}


# ----------------------------
# PDF generation and pipeline
# ----------------------------

def generate_pdf(markdown: Path, pdf_path: Path, css_path: Path, *, no_mathjax: bool) -> None:
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


def preprocess_broken_lists(md_path: Path, pdf_path: Path, css_path: Path, *, iterations: int, no_mathjax: bool) -> Dict:
    total_fixed = 0

    for iteration in range(1, iterations + 1):
        generate_pdf(md_path, pdf_path, css_path, no_mathjax=no_mathjax)
        check = find_broken_lists(md_path, pdf_path)
        if not check.get("success"):
            return check

        broken_lists = check.get("broken_lists", [])
        if not broken_lists:
            return {
                "success": True,
                "fixed_count": total_fixed,
                "iterations": iteration,
                "remaining_broken": 0,
                "message": f"All lists are rendering correctly after {iteration} iteration(s).",
            }

        fixed_this_round = 0
        for first_line in broken_lists:
            res = fix_broken_list(md_path, first_line)
            if res.get("success") and not res.get("already_exists"):
                fixed_this_round += 1

        total_fixed += fixed_this_round
        print(f"[lists] iteration {iteration}: fixed {fixed_this_round} / {len(broken_lists)}")

    # Final pass and summary
    generate_pdf(md_path, pdf_path, css_path, no_mathjax=no_mathjax)
    final_check = find_broken_lists(md_path, pdf_path)
    remaining_lists = final_check.get("broken_lists", []) if final_check.get("success") else []
    remaining = len(remaining_lists) if final_check.get("success") else -1

    return {
        "success": remaining == 0 if remaining >= 0 else False,
        "fixed_count": total_fixed,
        "iterations": iterations,
        "remaining_broken": remaining if remaining >= 0 else "unknown",
        "remaining_lists": remaining_lists,
        "message": final_check.get("message") if final_check.get("message") else "",
    }


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_json)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    output_md = args.output_md or input_path.with_suffix(".md")
    output_pdf = args.output_pdf or input_path.with_suffix(".pdf")

    with input_path.open("r", encoding=args.encoding) as handle:
        data: Any = json.load(handle)

    flattened = flatten(data, sep=args.separator)
    markdown = to_markdown(flattened)

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(markdown, encoding=args.encoding)
    print(f"[flatten] wrote {len(flattened)} sections to {output_md}")

    list_result = preprocess_broken_lists(
        output_md,
        output_pdf,
        args.css,
        iterations=args.max_iterations,
        no_mathjax=args.no_mathjax,
    )

    # Always emit final PDF; treat remaining broken lists as failure exit code.
    remaining = list_result.get("remaining_broken")
    if not list_result.get("success") or (isinstance(remaining, int) and remaining > 0):
        print(f"[lists] incomplete: {list_result}")
        raise SystemExit(1)

    print(f"[lists] {list_result}")
    print(f"[pdf] final PDF at {output_pdf.resolve()}")


if __name__ == "__main__":
    main()
