#!/usr/bin/env python3
"""
Pipeline: JSON -> flattened Markdown -> auto-fix line breaks -> PDF.

Steps:
1) Flatten JSON using the same logic as flatten_json_to_md.py
2) Auto-fix lines that collapse in the PDF by checking every markdown line
3) Render to PDF via md2pdf.py with css/custom.css by default
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber

from flatten_json_to_md import flatten, to_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Flatten a JSON file, fix collapsed markdown lines, and render to PDF."
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
        help="Maximum passes to fix collapsed lines (default: 1).",
    )
    parser.add_argument(
        "--no-mathjax",
        action="store_true",
        help="Disable MathJax when calling md2pdf.py (faster if not needed).",
    )
    return parser.parse_args()


# ----------------------------
# Markdown helpers
# ----------------------------

def _is_bullet_line(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("-", "*", "+")) and len(stripped) > 1 and stripped[1].isspace()


def _is_numbered_line(line: str) -> bool:
    stripped = line.lstrip()
    return bool(re.match(r"^\d+[.)]\s+", stripped))


def _is_list_line(line: str) -> bool:
    return _is_bullet_line(line) or _is_numbered_line(line)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", text).lower()


def _strip_markdown_formatting(line: str) -> str:
    """Strip markdown markers so we can compare text-only content against PDF output."""
    stripped = line.strip()
    stripped = re.sub(r"^#{1,6}\s+", "", stripped)  # headings
    stripped = re.sub(r"^>\s+", "", stripped)  # blockquotes
    stripped = re.sub(r"^(\*|-|\+)\s+", "", stripped)  # bullets
    stripped = re.sub(r"^\d+[.)]\s+", "", stripped)  # numbered lists
    stripped = re.sub(r"`([^`]*)`", r"\1", stripped)  # inline code
    stripped = stripped.replace("**", "").replace("__", "")
    stripped = stripped.replace("*", "").replace("_", "")
    stripped = stripped.replace("~~", "")
    return stripped.strip()


def _match_in_pdf_lines(pdf_norm_lines: List[str], start_idx: int, expected_norm: str, *, max_window: int = 3) -> Optional[int]:
    """
    Try to find expected_norm across up to `max_window` consecutive PDF lines starting
    at or after start_idx. Returns the next index after the matched window, or None if not found.
    """
    if not expected_norm:
        return start_idx

    n = len(pdf_norm_lines)
    for j in range(start_idx, n):
        for window in range(1, max_window + 1):
            end = j + window
            if end > n:
                break
            window_text = "".join(pdf_norm_lines[j:end])
            if expected_norm in window_text:
                return end
    return None


def _is_first_list_item(lines: List[str], idx: int) -> bool:
    if not _is_list_line(lines[idx]):
        return False

    prev = idx - 1
    while prev >= 0 and lines[prev].strip() == "":
        prev -= 1

    return prev < 0 or not _is_list_line(lines[prev])


def _find_list_end(lines: List[str], start_idx: int) -> int:
    end = start_idx + 1
    while end < len(lines) and _is_list_line(lines[end]):
        end += 1
    return end


# ----------------------------
# Line mismatch detection/fix
# ----------------------------

def find_line_mismatches(md_path: Path, pdf_path: Path) -> Dict[str, Any]:
    if not md_path.exists():
        return {"success": False, "error": f"Markdown not found: {md_path}"}
    if not pdf_path.exists():
        return {"success": False, "error": f"PDF not found: {pdf_path}"}

    md_lines = md_path.read_text(encoding="utf-8").splitlines()

    pdf_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pdf_text += page.extract_text() or ""
            pdf_text += "\n"

    pdf_norm_lines = [_normalize(line) for line in pdf_text.splitlines()]
    mismatches: List[Dict[str, Any]] = []
    pdf_idx = 0

    for i, line in enumerate(md_lines):
        if not line.strip():
            continue

        expected_text = _strip_markdown_formatting(line)
        expected_norm = _normalize(expected_text)
        if not expected_norm:
            continue

        next_idx = _match_in_pdf_lines(pdf_norm_lines, pdf_idx, expected_norm)
        if next_idx is not None:
            pdf_idx = next_idx
            continue

        is_list = _is_list_line(line)
        mismatches.append(
            {
                "line_index": i,
                "line_text": line,
                "expected_norm": expected_norm,
                "is_list_item": is_list,
                "is_first_list_item": is_list and _is_first_list_item(md_lines, i),
                "list_end": _find_list_end(md_lines, i) if is_list else i + 1,
            }
        )

    return {
        "success": True,
        "mismatches": mismatches,
        "broken_count": len(mismatches),
        "total_count": len([l for l in md_lines if l.strip()]),
    }


def apply_line_fixes(md_path: Path, mismatches: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not md_path.exists():
        return {"success": False, "error": f"Markdown not found: {md_path}"}

    if not mismatches:
        return {"success": True, "fixed": 0}

    lines = md_path.read_text(encoding="utf-8").splitlines(keepends=True)
    fixed = 0
    offset = 0
    skip_until = -1

    for mismatch in mismatches:
        idx = mismatch["line_index"] + offset
        if idx < skip_until:
            continue

        if mismatch.get("is_first_list_item"):
            if idx > 0 and lines[idx - 1].strip() == "":
                skip_until = mismatch.get("list_end", idx + 1) + offset
                continue

            lines.insert(idx, "\n")
            fixed += 1
            offset += 1
            skip_until = mismatch.get("list_end", idx + 1) + offset
            continue

        if idx == 0:
            continue

        prev_line = lines[idx - 1]
        if prev_line.rstrip("\n").endswith("  "):
            continue

        if prev_line.endswith("\n"):
            lines[idx - 1] = prev_line[:-1] + "  \n"
        else:
            lines[idx - 1] = prev_line + "  "
        fixed += 1

    if fixed > 0:
        md_path.write_text("".join(lines), encoding="utf-8")

    return {"success": True, "fixed": fixed}


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


def preprocess_line_breaks(md_path: Path, pdf_path: Path, css_path: Path, *, iterations: int, no_mathjax: bool) -> Dict[str, Any]:
    total_fixed = 0

    for iteration in range(1, iterations + 1):
        generate_pdf(md_path, pdf_path, css_path, no_mathjax=no_mathjax)
        check = find_line_mismatches(md_path, pdf_path)
        if not check.get("success"):
            return check

        mismatches = check.get("mismatches", [])
        if not mismatches:
            return {
                "success": True,
                "fixed_count": total_fixed,
                "iterations": iteration,
                "remaining_broken": 0,
                "message": f"All lines render separately after {iteration} iteration(s).",
            }

        fix_res = apply_line_fixes(md_path, mismatches)
        fixed_this_round = fix_res.get("fixed", 0) if fix_res.get("success") else 0
        total_fixed += fixed_this_round
        print(f"[lines] iteration {iteration}: fixed {fixed_this_round} / {len(mismatches)}")

        if fixed_this_round == 0:
            return {
                "success": False,
                "fixed_count": total_fixed,
                "iterations": iteration,
                "remaining_broken": len(mismatches),
                "message": "No fixes applied; remaining lines still collapsed.",
            }

    # Final pass and summary
    generate_pdf(md_path, pdf_path, css_path, no_mathjax=no_mathjax)
    final_check = find_line_mismatches(md_path, pdf_path)
    remaining = final_check.get("broken_count", -1) if final_check.get("success") else -1

    return {
        "success": remaining == 0 if remaining >= 0 else False,
        "fixed_count": total_fixed,
        "iterations": iterations,
        "remaining_broken": remaining if remaining >= 0 else "unknown",
        "remaining_lines": final_check.get("mismatches", []),
        "message": final_check.get("message", ""),
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

    line_result = preprocess_line_breaks(
        output_md,
        output_pdf,
        args.css,
        iterations=args.max_iterations,
        no_mathjax=args.no_mathjax,
    )

    remaining = line_result.get("remaining_broken")
    if not line_result.get("success") or (isinstance(remaining, int) and remaining > 0):
        print(f"[lines] incomplete: {line_result}")
        raise SystemExit(1)

    print(f"[lines] {line_result}")
    print(f"[pdf] final PDF at {output_pdf.resolve()}")


if __name__ == "__main__":
    main()
