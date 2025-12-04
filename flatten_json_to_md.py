#!/usr/bin/env python3
"""Flatten a JSON file into dot-notated Markdown sections."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Flatten a JSON file and emit a Markdown document with one section per key."
    )
    parser.add_argument(
        "input_json",
        nargs="?",
        default="docs/research_ArtCentrica.json",
        help="Path to the input JSON file (default: docs/research_ArtCentrica.json).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output Markdown path (defaults to replacing the input extension with .md).",
    )
    parser.add_argument(
        "--separator",
        default=".",
        help="Separator for nested object keys (default: '.').",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Encoding to use for reading and writing files (default: utf-8).",
    )
    return parser.parse_args()


def flatten(value: Any, *, parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    """Flatten nested dicts/lists into a single level using dot-and-index notation."""
    flattened: Dict[str, Any] = {}

    def _walk(current: Any, key_prefix: str) -> None:
        if isinstance(current, dict):
            for key, val in current.items():
                new_key = f"{key_prefix}{sep}{key}" if key_prefix else str(key)
                _walk(val, new_key)
        elif isinstance(current, list):
            for idx, val in enumerate(current):
                new_key = f"{key_prefix}[{idx}]" if key_prefix else f"[{idx}]"
                _walk(val, new_key)
        else:
            final_key = key_prefix or "<root>"
            flattened[final_key] = current

    _walk(value, parent_key)
    return flattened


def format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def to_markdown(flattened: Dict[str, Any]) -> str:
    """Render the flattened mapping into Markdown sections."""
    lines = []
    total = len(flattened)

    for idx, (key, val) in enumerate(flattened.items()):
        lines.append(f"## {key}\n\n")
        lines.append(f"{format_value(val)}\n")
        if idx != total - 1:
            lines.append("\n---\n\n")

    return "".join(lines)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_json)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    output_path = Path(args.output) if args.output else input_path.with_suffix(".md")

    with input_path.open("r", encoding=args.encoding) as handle:
        data = json.load(handle)

    flattened = flatten(data, sep=args.separator)
    markdown = to_markdown(flattened)

    with output_path.open("w", encoding=args.encoding) as handle:
        handle.write(markdown)

    print(f"Wrote {len(flattened)} sections to {output_path}")


if __name__ == "__main__":
    main()
