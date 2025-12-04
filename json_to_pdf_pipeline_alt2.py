#!/usr/bin/env python3
"""
Pipeline: JSON -> flattened Markdown -> auto-fix broken line rendering -> PDF.

Steps:
1) Flatten JSON using the same logic as flatten_json_to_md.py
2) Auto-fix lines not rendering on their own line in PDF
3) Render to PDF via md2pdf.py with css/custom.css by default
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

from flatten_json_to_md import flatten, to_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Flatten a JSON file, fix broken markdown lines, and render to PDF."
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
        default=3,
        help="Maximum passes to fix broken lines (default: 3).",
    )
    parser.add_argument(
        "--no-mathjax",
        action="store_true",
        help="Disable MathJax when calling md2pdf.py (faster if not needed).",
    )
    return parser.parse_args()


# ----------------------------
# Markdown line type detection
# ----------------------------

def _normalize(s: str) -> str:
    """Remove all non-alphanumeric characters for fuzzy matching."""
    return re.sub(r"[^a-zA-Z0-9]", "", s)


def _is_blank_line(line: str) -> bool:
    return line.strip() == ""


def _is_horizontal_rule(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r'^(-{3,}|\*{3,}|_{3,})$', stripped))


def _is_heading(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#")


def _is_bullet_line(line: str) -> bool:
    stripped = line.lstrip()
    return bool(re.match(r'^[-*+]\s+', stripped))


def _is_numbered_list_line(line: str) -> bool:
    stripped = line.lstrip()
    return bool(re.match(r'^\d+[.)]\s+', stripped))


def _is_list_line(line: str) -> bool:
    return _is_bullet_line(line) or _is_numbered_list_line(line)


def _is_blockquote(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(">")


def _is_code_fence(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def _extract_visible_text(line: str) -> str:
    """
    Extract the visible text from a markdown line, stripping markdown syntax.
    Returns the text that would appear in the rendered PDF.
    """
    stripped = line.strip()
    if not stripped:
        return ""
    
    # Remove heading markers (but keep the text)
    if stripped.startswith("#"):
        stripped = re.sub(r'^#+\s*', '', stripped)
    
    # Remove bullet markers (bullets render as symbols, not dashes)
    stripped = re.sub(r'^[-*+]\s+', '', stripped)
    
    # NOTE: Do NOT remove numbered list markers - they appear in the PDF as "1.", "2.", etc.
    # stripped = re.sub(r'^\d+[.)]\s+', '', stripped)  # REMOVED
    
    # Remove blockquote markers
    stripped = re.sub(r'^>\s*', '', stripped)
    
    # Remove HTML-like tags (e.g., <qid>, <tag>, etc.)
    stripped = re.sub(r'<[^>]+>', '', stripped)
    
    # Remove bold/italic markers but keep content
    stripped = re.sub(r'\*\*([^*]+)\*\*', r'\1', stripped)
    stripped = re.sub(r'\*([^*]+)\*', r'\1', stripped)
    stripped = re.sub(r'__([^_]+)__', r'\1', stripped)
    stripped = re.sub(r'_([^_]+)_', r'\1', stripped)
    
    # Remove inline code markers
    stripped = re.sub(r'`([^`]+)`', r'\1', stripped)
    
    # Remove link syntax, keep text
    stripped = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', stripped)
    
    # Clean up extra whitespace from removals
    stripped = re.sub(r'\s+', ' ', stripped)
    
    return stripped.strip()


def _get_line_signature(line: str, num_words: int = 5) -> str:
    """
    Get a normalized signature of the first N words of a line's visible text.
    Used for matching lines between markdown and PDF.
    """
    text = _extract_visible_text(line)
    words = text.split()[:num_words]
    return _normalize(" ".join(words)).lower()


def _get_full_signature(line: str) -> str:
    """
    Get a normalized signature of the FULL visible text of a line.
    Used for exact matching of short lines.
    """
    text = _extract_visible_text(line)
    return _normalize(text).lower()


def _is_list_continuation(line: str) -> bool:
    """Check if line is a continuation of a list item (indented content)."""
    # Continuation lines start with at least 2-3 spaces of indentation
    return line.startswith("   ") or line.startswith("\t")


def _find_list_start(lines: List[str], idx: int) -> int:
    """
    Given a list line at idx, find the index of the first line of this list.
    Returns idx if it's already the first line of the list.
    Accounts for continuation lines (indented content under list items).
    """
    if idx == 0:
        return idx
    
    # Walk backwards to find the start of this list
    i = idx - 1
    while i >= 0:
        if _is_blank_line(lines[i]):
            # Blank line - this line is the start of a new list
            return idx if i == idx - 1 else i + 1
        if _is_list_line(lines[i]):
            # Previous line is also a list item - keep going back
            i -= 1
            continue
        if _is_list_continuation(lines[i]):
            # This is indented content under a list item - keep going back
            i -= 1
            continue
        # Non-list, non-blank, non-continuation line - next line is list start
        return i + 1
    return 0


def _find_list_end(lines: List[str], idx: int) -> int:
    """
    Given a list line at idx, find the index of the last line of this list.
    Accounts for continuation lines (indented content under list items).
    """
    n = len(lines)
    i = idx + 1
    while i < n:
        if _is_blank_line(lines[i]):
            # Blank line ends the list
            return i - 1
        if _is_list_line(lines[i]):
            # Another list item - continue
            i += 1
            continue
        if _is_list_continuation(lines[i]):
            # Continuation line (indented content) - continue
            i += 1
            continue
        # Non-list, non-blank, non-continuation line - previous line was list end
        return i - 1
    return n - 1


# ----------------------------
# Line-by-line checking
# ----------------------------

def extract_checkable_lines(md_content: str) -> List[Tuple[int, str, str]]:
    """
    Extract all lines that should be checked for proper rendering.
    Returns list of (line_index, original_line, signature).
    
    Skips:
    - Blank lines
    - Horizontal rules
    - Code blocks (inside fences)
    """
    lines = md_content.splitlines()
    result: List[Tuple[int, str, str]] = []
    in_code_block = False
    
    for i, line in enumerate(lines):
        # Track code blocks
        if _is_code_fence(line):
            in_code_block = not in_code_block
            continue
        
        if in_code_block:
            continue
        
        if _is_blank_line(line):
            continue
        
        if _is_horizontal_rule(line):
            continue
        
        sig = _get_line_signature(line)
        if sig:  # Only include lines with actual content
            result.append((i, line, sig))
    
    return result


def extract_pdf_lines(pdf_path: Path) -> List[Tuple[str, str]]:
    """
    Extract all text lines from the PDF.
    Returns list of (original_line, normalized_signature).
    """
    pdf_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pdf_text += page.extract_text() or ""
            pdf_text += "\n"
    
    result: List[Tuple[str, str]] = []
    for line in pdf_text.splitlines():
        stripped = line.strip()
        if stripped:
            sig = _normalize(stripped).lower()
            result.append((stripped, sig))
    
    return result


def find_broken_lines(md_path: Path, pdf_path: Path) -> Dict:
    """
    Check every markdown line to see if it renders on its own line in the PDF.
    Returns info about broken lines and their fix types.
    """
    if not md_path.exists():
        return {"success": False, "error": f"Markdown not found: {md_path}"}
    if not pdf_path.exists():
        return {"success": False, "error": f"PDF not found: {pdf_path}"}
    
    md_content = md_path.read_text(encoding="utf-8")
    md_lines = md_content.splitlines()
    checkable = extract_checkable_lines(md_content)
    pdf_lines = extract_pdf_lines(pdf_path)
    
    if not checkable:
        return {
            "success": True,
            "broken_lines": [],
            "total_checked": 0,
            "message": "No checkable lines found",
        }
    
    # Build a set of PDF line signatures for quick lookup
    pdf_sigs = {sig for _, sig in pdf_lines}
    
    broken: List[Dict] = []
    correct_count = 0
    skip_until_idx = -1  # For skipping rest of a list after fixing first item
    
    for i, (line_idx, line, sig) in enumerate(checkable):
        if line_idx <= skip_until_idx:
            continue
        
        # For short signatures, use full line matching to avoid false positives
        # (e.g., "Evidence:" appears at end of many lines but we need it on its own line)
        full_sig = _get_full_signature(line)
        use_exact_match = len(sig) < 15  # Short signatures need exact matching
        
        # Check if this line's signature appears at the start of any PDF line
        line_found = False
        for pdf_orig, pdf_sig in pdf_lines:
            if not pdf_sig:
                continue
            if use_exact_match:
                # For short lines, require the PDF line to match the full signature
                # (PDF line should start with our content, or be exactly our content)
                if pdf_sig == full_sig or pdf_sig.startswith(full_sig):
                    line_found = True
                    break
            else:
                # For longer lines, prefix matching is fine
                if pdf_sig.startswith(sig) or sig.startswith(pdf_sig[:len(sig)]):
                    line_found = True
                    break
        
        if line_found:
            correct_count += 1
            continue
        
        # Line not found - determine fix type
        is_list = _is_list_line(line)
        list_start_idx = _find_list_start(md_lines, line_idx) if is_list else -1
        is_first_of_list = is_list and (list_start_idx == line_idx)
        
        if is_first_of_list:
            # Fix type A: insert blank line before first list item
            fix_type = "insert_blank_before"
            list_end_idx = _find_list_end(md_lines, line_idx)
            skip_until_idx = list_end_idx  # Skip rest of this list
        else:
            # Fix type B: append two spaces to previous line
            fix_type = "append_spaces_to_prev"
        
        broken.append({
            "line_idx": line_idx,
            "line": line,
            "signature": sig,
            "fix_type": fix_type,
            "is_list": is_list,
            "is_first_of_list": is_first_of_list,
        })
    
    return {
        "success": True,
        "broken_lines": broken,
        "correct_count": correct_count,
        "total_checked": len(checkable),
        "broken_count": len(broken),
    }


def apply_fixes(md_path: Path, broken_lines: List[Dict]) -> Dict:
    """
    Apply fixes to the markdown file for all broken lines.
    Returns count of fixes applied.
    """
    if not broken_lines:
        return {"success": True, "fixed_count": 0}
    
    content = md_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    # Sort by line index descending so we can modify without shifting indices
    sorted_broken = sorted(broken_lines, key=lambda x: x["line_idx"], reverse=True)
    
    fixed_count = 0
    for item in sorted_broken:
        line_idx = item["line_idx"]
        fix_type = item["fix_type"]
        
        if fix_type == "insert_blank_before":
            # Check if blank line already exists
            if line_idx > 0 and lines[line_idx - 1].strip() == "":
                continue
            lines.insert(line_idx, "")
            fixed_count += 1
        
        elif fix_type == "append_spaces_to_prev":
            if line_idx > 0:
                prev_line = lines[line_idx - 1]
                # Don't add spaces if already ends with 2+ spaces or is blank
                if not prev_line.endswith("  ") and prev_line.strip():
                    lines[line_idx - 1] = prev_line.rstrip() + "  "
                    fixed_count += 1
    
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"success": True, "fixed_count": fixed_count}


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


def preprocess_broken_lines(md_path: Path, pdf_path: Path, css_path: Path, *, iterations: int, no_mathjax: bool) -> Dict:
    """
    Iteratively find and fix lines that don't render on their own line in the PDF.
    """
    total_fixed = 0

    for iteration in range(1, iterations + 1):
        generate_pdf(md_path, pdf_path, css_path, no_mathjax=no_mathjax)
        check = find_broken_lines(md_path, pdf_path)
        if not check.get("success"):
            return check

        broken = check.get("broken_lines", [])
        if not broken:
            return {
                "success": True,
                "fixed_count": total_fixed,
                "iterations": iteration,
                "remaining_broken": 0,
                "total_checked": check.get("total_checked", 0),
                "message": f"All lines rendering correctly after {iteration} iteration(s).",
            }

        fix_result = apply_fixes(md_path, broken)
        fixed_this_round = fix_result.get("fixed_count", 0)
        total_fixed += fixed_this_round
        
        print(f"[lines] iteration {iteration}: fixed {fixed_this_round} / {len(broken)} broken lines")

    # Final pass and summary
    generate_pdf(md_path, pdf_path, css_path, no_mathjax=no_mathjax)
    final_check = find_broken_lines(md_path, pdf_path)
    remaining = final_check.get("broken_count", -1) if final_check.get("success") else -1
    remaining_lines = final_check.get("broken_lines", []) if final_check.get("success") else []

    return {
        "success": remaining == 0 if remaining >= 0 else False,
        "fixed_count": total_fixed,
        "iterations": iterations,
        "remaining_broken": remaining if remaining >= 0 else "unknown",
        "remaining_lines": remaining_lines[:10],  # Limit output
        "total_checked": final_check.get("total_checked", 0),
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

    result = preprocess_broken_lines(
        output_md,
        output_pdf,
        args.css,
        iterations=args.max_iterations,
        no_mathjax=args.no_mathjax,
    )

    # Always emit final PDF; treat remaining broken lines as failure exit code.
    remaining = result.get("remaining_broken")
    if not result.get("success") or (isinstance(remaining, int) and remaining > 0):
        print(f"[lines] incomplete: {result}")
        raise SystemExit(1)

    print(f"[lines] {result}")
    print(f"[pdf] final PDF at {output_pdf.resolve()}")


if __name__ == "__main__":
    main()
