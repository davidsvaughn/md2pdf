#!/usr/bin/env python3
"""
Convert Markdown to PDF with Apostrophe's preview styling.
Requires pandoc on PATH and weasyprint Python package.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from weasyprint import HTML


THEMES = {
    "adwaita": "css/adwaita.css",
    "adwaita-sepia": "css/adwaita-sepia.css",
    "highcontrast": "css/highcontrast.css",
    "highcontrast_inverse": "css/highcontrast_inverse.css",
}


def here() -> Path:
    return Path(__file__).resolve().parent


def ensure_tool(tool: str) -> None:
    if not shutil.which(tool):
        sys.exit(f"Missing dependency: '{tool}' not found in PATH.")


def inline_css(css_path: Path) -> str:
    """Read CSS and inline any @import of sibling files."""
    css_dir = css_path.parent
    css = css_path.read_text(encoding="utf-8")

    def replace_import(match: re.Match) -> str:
        rel_path = match.group(1)
        imported = (css_dir / rel_path).resolve()
        if imported.is_file():
            return imported.read_text(encoding="utf-8")
        return match.group(0)

    css = re.sub(r'@import url\("(.*?)"\);', replace_import, css)
    return css


def build_html(markdown: Path, css: Path, mathjax: bool) -> str:
    pandoc_args = [
        "pandoc",
        "--standalone",
        "--to",
        "html5",
        "--self-contained",
        f"--css={css}",
        "--lua-filter",
        str(here() / "lua/relative_to_absolute.lua"),
        "--lua-filter",
        str(here() / "lua/task-list.lua"),
    ]

    if mathjax:
        pandoc_args.append("--mathjax")

    pandoc_args.append(str(markdown))

    result = subprocess.run(
        pandoc_args,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit("Pandoc failed; see errors above.")

    html = result.stdout

    # Inline CSS for better PDF rendering.
    css_text = inline_css(css)
    html = re.sub(r'<link rel="stylesheet"[^>]*>', "", html, flags=re.IGNORECASE)
    html = html.replace("</head>", f"<style>\n{css_text}\n</style>\n</head>", 1)

    return html


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    """Convert HTML file to PDF using WeasyPrint."""
    try:
        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    except Exception as e:
        sys.exit(f"WeasyPrint failed: {e}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Markdown to PDF with Apostrophe preview styling.")
    parser.add_argument("input", type=Path, help="Markdown input file")
    parser.add_argument("output", type=Path, help="PDF output file")
    parser.add_argument(
        "--theme",
        choices=THEMES.keys(),
        default="adwaita",
        help="CSS theme to use (default: adwaita)",
    )
    parser.add_argument(
        "--css",
        type=Path,
        help="Override CSS file path (absolute). Takes precedence over --theme.",
    )
    parser.add_argument(
        "--html-out",
        type=Path,
        help="Save intermediate HTML to this path instead of a temp file.",
    )
    parser.add_argument(
        "--no-mathjax",
        action="store_true",
        help="Disable MathJax support (faster if you do not need math).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_tool("pandoc")

    css_path = args.css
    if css_path is None:
        css_rel = THEMES[args.theme]
        css_path = here() / css_rel
    css_path = css_path.resolve()

    if not css_path.is_file():
        sys.exit(f"CSS file not found: {css_path}")

    html_content = build_html(
        args.input.resolve(),
        css_path,
        mathjax=not args.no_mathjax,
    )

    if args.html_out:
        html_path = args.html_out.resolve()
        html_path.write_text(html_content, encoding="utf-8")
    else:
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
        html_path = Path(temp.name)
        temp.write(html_content.encode("utf-8"))
        temp.close()

    try:
        html_to_pdf(html_path, args.output.resolve())
    finally:
        if not args.html_out and html_path.exists():
            html_path.unlink()


if __name__ == "__main__":
    main()
