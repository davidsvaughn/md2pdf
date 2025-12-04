"""
Tools for the PDF improvement agent using OpenAI Agents SDK.
Simple functions that the agent can call to read files, edit them, and generate PDFs.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List
from pdf2image import convert_from_path
from PIL import Image
import io
import difflib
import re

from agents import function_tool

# Working directory paths
WORK_DIR = Path(__file__).parent
MD_FILE = WORK_DIR / "document.md"
CSS_FILE = WORK_DIR / "custom.css"
PDF_FILE = WORK_DIR / "output.pdf"
SNAPSHOT_DIR = WORK_DIR / "snapshots"

# Ensure snapshot directory exists
SNAPSHOT_DIR.mkdir(exist_ok=True)

# Track snapshot counter
_snapshot_counter = 0


@function_tool
def read_file(file_type: str) -> Dict:
    """Read markdown or CSS file with context.
    
    Args:
        file_type: "markdown" or "css"
    
    Returns:
        {
            'content': str,  # full file text
            'line_count': int,
            'size_kb': float
        }
    """
    file_path = MD_FILE if file_type == "markdown" else CSS_FILE
    
    if not file_path.exists():
        return {
            'success': False,
            'error': f'{file_type} file not found at {file_path}'
        }
    
    content = file_path.read_text(encoding='utf-8')
    size_kb = len(content.encode('utf-8')) / 1024
    
    return {
        'success': True,
        'content': content,
        'line_count': len(content.splitlines()),
        'size_kb': round(size_kb, 2)
    }


@function_tool
def insert_blank_line_before(file_type: str, search_text: str) -> Dict:
    """Insert blank line before first occurrence.
    Common fix for markdown list parsing issues.
    
    Args:
        file_type: "markdown" or "css"
        search_text: Text to search for (case-insensitive fuzzy matching)
    
    Returns:
        {
            'success': bool,
            'line_number': int,
            'context': str  # 3 lines before/after
        }
    """
    # Auto-save snapshot before modification
    save_snapshot(description=f"before insert_blank_line in {file_type}")
    
    file_path = MD_FILE if file_type == "markdown" else CSS_FILE
    
    if not file_path.exists():
        return {
            'success': False,
            'error': f'{file_type} file not found'
        }
    
    content = file_path.read_text(encoding='utf-8')
    lines = content.splitlines(keepends=True)
    
    # Find first occurrence (case-insensitive)
    search_lower = search_text.lower()
    found_line = -1
    
    for i, line in enumerate(lines):
        if search_lower in line.lower():
            found_line = i
            break
    
    if found_line == -1:
        return {
            'success': False,
            'error': f'Text not found: "{search_text}"'
        }
    
    # Don't insert if there's already a blank line before
    if found_line > 0 and lines[found_line - 1].strip() == '':
        return {
            'success': True,
            'already_exists': True,
            'line_number': found_line + 1,
            'message': 'Blank line already exists before this line'
        }
    
    # Insert blank line
    lines.insert(found_line, '\n')
    
    # Write back
    file_path.write_text(''.join(lines), encoding='utf-8')
    
    # Get context
    start = max(0, found_line - 2)
    end = min(len(lines), found_line + 5)
    context_lines = lines[start:end]
    context = ''.join(context_lines)
    
    return {
        'success': True,
        'line_number': found_line + 1,
        'context': context,
        'message': f'Inserted blank line before line {found_line + 1}'
    }


@function_tool
def insert_page_break_before(search_text: str) -> Dict:
    """Insert a page break before the specified text in the markdown file.
    
    Use this to force content to start on a new page. Useful for:
    - Starting a new section on a fresh page
    - Avoiding awkward page breaks in the middle of content
    
    Args:
        search_text: Text to search for (the page break will be inserted before this line)
    
    Returns:
        {
            'success': bool,
            'line_number': int,
            'message': str
        }
    """
    save_snapshot(description=f"before insert_page_break")
    
    if not MD_FILE.exists():
        return {'success': False, 'error': 'Markdown file not found'}
    
    content = MD_FILE.read_text(encoding='utf-8')
    lines = content.splitlines(keepends=True)
    
    # Find the line containing the search text
    search_lower = search_text.lower()
    found_line = -1
    
    for i, line in enumerate(lines):
        if search_lower in line.lower():
            found_line = i
            break
    
    if found_line == -1:
        return {'success': False, 'error': f'Text not found: "{search_text}"'}
    
    # Insert page break div before the found line
    page_break_html = '<div style="page-break-before: always;"></div>\n\n'
    lines.insert(found_line, page_break_html)
    
    # Write back
    MD_FILE.write_text(''.join(lines), encoding='utf-8')
    
    return {
        'success': True,
        'line_number': found_line + 1,
        'message': f'Inserted page break before line {found_line + 1}'
    }


@function_tool
def insert_vertical_space_before(search_text: str, amount: str = "2em") -> Dict:
    """Insert vertical spacing before the specified text in the markdown file.
    
    Use this to add space before specific content. Useful for:
    - Pushing content down to avoid awkward page breaks
    - Adding breathing room before sections
    - Nudging a heading to the next page
    
    Args:
        search_text: Text to search for (space will be inserted before this line)
        amount: CSS size value for the space (e.g., "1em", "2em", "20px", "0.5in")
    
    Returns:
        {
            'success': bool,
            'line_number': int,
            'message': str
        }
    """
    save_snapshot(description=f"before insert_vertical_space")
    
    if not MD_FILE.exists():
        return {'success': False, 'error': 'Markdown file not found'}
    
    content = MD_FILE.read_text(encoding='utf-8')
    lines = content.splitlines(keepends=True)
    
    # Find the line containing the search text
    search_lower = search_text.lower()
    found_line = -1
    
    for i, line in enumerate(lines):
        if search_lower in line.lower():
            found_line = i
            break
    
    if found_line == -1:
        return {'success': False, 'error': f'Text not found: "{search_text}"'}
    
    # Insert spacer div before the found line
    spacer_html = f'<div style="margin-top: {amount};"></div>\n\n'
    lines.insert(found_line, spacer_html)
    
    # Write back
    MD_FILE.write_text(''.join(lines), encoding='utf-8')
    
    return {
        'success': True,
        'line_number': found_line + 1,
        'amount': amount,
        'message': f'Inserted {amount} vertical space before line {found_line + 1}'
    }


@function_tool
def modify_css_property(selector: str, property: str, value: str) -> Dict:
    """Add or update CSS property for a selector.
    
    Args:
        selector: CSS selector (e.g., "@page", "h2", ".section")
        property: CSS property name (e.g., "margin-top")
        value: New value (e.g., "0.5em")
    
    Returns:
        {
            'success': bool,
            'action': 'added' | 'updated',
            'full_rule': str  # the complete CSS rule
        }
    """
    # Enforce minimum page margin of 0.4in
    if selector == "@page" and property == "margin":
        # Parse the value to check if it's below minimum
        val_lower = value.lower().strip()
        try:
            if val_lower.endswith('in'):
                num = float(val_lower[:-2])
                if num < 0.4:
                    value = "0.4in"  # Enforce minimum
            elif val_lower.endswith('cm'):
                num = float(val_lower[:-2])
                if num < 1.0:  # ~0.4in = ~1cm
                    value = "0.4in"
        except ValueError:
            pass  # Keep original value if parsing fails
    
    # Auto-save snapshot before modification
    save_snapshot(description=f"before modify_css {selector}")
    
    if not CSS_FILE.exists():
        return {
            'success': False,
            'error': 'CSS file not found'
        }
    
    content = CSS_FILE.read_text(encoding='utf-8')
    
    # Simple CSS parsing - look for selector block
    # Pattern to find existing selector block
    pattern = re.compile(
        rf'({re.escape(selector)}\s*\{{[^}}]*\}})',
        re.MULTILINE | re.DOTALL
    )
    
    match = pattern.search(content)
    
    if match:
        # Selector exists - update property
        block = match.group(1)
        
        # Check if property exists in block
        prop_pattern = re.compile(
            rf'{re.escape(property)}\s*:\s*[^;]+;',
            re.MULTILINE
        )
        
        if prop_pattern.search(block):
            # Update existing property
            new_block = prop_pattern.sub(f'{property}: {value};', block)
            action = 'updated'
        else:
            # Add new property to existing block
            new_block = block.replace('}', f'  {property}: {value};\n}}')
            action = 'added'
        
        content = content.replace(block, new_block)
        full_rule = new_block
    else:
        # Create new selector block
        new_rule = f'\n{selector} {{\n  {property}: {value};\n}}\n'
        content += new_rule
        full_rule = new_rule
        action = 'added'
    
    CSS_FILE.write_text(content, encoding='utf-8')
    
    return {
        'success': True,
        'action': action,
        'full_rule': full_rule,
        'message': f'{action.capitalize()} property {property} for {selector}'
    }


def generate_pdf() -> Dict:
    """Generate PDF from current markdown and CSS.
    Called directly by agent orchestration code.
    
    Returns:
        {
            'success': bool,
            'pdf_path': str,
            'page_count': int,
            'error': str | None
        }
    """
    if not MD_FILE.exists():
        return {
            'success': False,
            'error': 'Markdown file not found'
        }
    
    if not CSS_FILE.exists():
        return {
            'success': False,
            'error': 'CSS file not found'
        }
    
    # Call md2pdf.py from parent directory
    md2pdf_script = WORK_DIR.parent / "md2pdf.py"
    
    try:
        result = subprocess.run(
            [
                'python', str(md2pdf_script),
                str(MD_FILE),
                str(PDF_FILE),
                '--css', str(CSS_FILE)
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(WORK_DIR.parent)  # Run from parent dir so CSS imports work
        )
        
        if result.returncode != 0:
            error_msg = f'PDF generation failed (exit code {result.returncode})'
            if result.stderr:
                error_msg += f'\nSTDERR: {result.stderr}'
            if result.stdout:
                error_msg += f'\nSTDOUT: {result.stdout}'
            return {
                'success': False,
                'error': error_msg
            }
        
        if not PDF_FILE.exists():
            return {
                'success': False,
                'error': 'PDF file was not created'
            }
        
        # Count pages by converting to images
        try:
            images = convert_from_path(str(PDF_FILE), dpi=72)
            page_count = len(images)
        except Exception as e:
            page_count = 0  # Unknown
        
        return {
            'success': True,
            'pdf_path': str(PDF_FILE),
            'page_count': page_count,
            'message': f'PDF generated successfully with {page_count} pages'
        }
        
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'PDF generation timed out after 30 seconds'
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }


def get_pdf_images() -> List[bytes]:
    """Convert PDF pages to JPEG bytes for vision analysis.
    
    Returns list of image bytes (1024x1024 JPEG).
    This is NOT a function_tool - it's used internally by the agent script.
    """
    if not PDF_FILE.exists():
        return []
    
    try:
        # Convert PDF to images (150 DPI for good quality)
        images = convert_from_path(str(PDF_FILE), dpi=150)
        
        image_bytes_list = []
        
        for img in images:
            # Resize to max 1024x1024 while maintaining aspect ratio
            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            
            # Convert to JPEG bytes
            buffer = io.BytesIO()
            img.convert('RGB').save(buffer, format='JPEG', quality=85)
            image_bytes_list.append(buffer.getvalue())
        
        return image_bytes_list
        
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return []


def save_snapshot(description: str = "") -> Dict:
    """Save current state (auto-called before edits).
    
    Args:
        description: Optional description of what's about to change
    
    Returns:
        {
            'snapshot_id': str,
            'timestamp': str
        }
    """
    global _snapshot_counter
    _snapshot_counter += 1
    
    snapshot_id = f"snapshot_{_snapshot_counter:03d}"
    snapshot_path = SNAPSHOT_DIR / snapshot_id
    snapshot_path.mkdir(exist_ok=True)
    
    # Copy files
    if MD_FILE.exists():
        shutil.copy2(MD_FILE, snapshot_path / "document.md")
    if CSS_FILE.exists():
        shutil.copy2(CSS_FILE, snapshot_path / "custom.css")
    
    # Save description
    if description:
        (snapshot_path / "description.txt").write_text(description)
    
    from datetime import datetime
    timestamp = datetime.now().isoformat()
    
    return {
        'success': True,
        'snapshot_id': snapshot_id,
        'timestamp': timestamp,
        'description': description
    }


def list_changes() -> Dict:
    """Show what changed since last snapshot.
    Called directly by agent orchestration code.
    
    Returns:
        {
            'markdown_changes': int,  # lines changed
            'css_changes': int,
            'diff_preview': str  # first 10 changes
        }
    """
    # Find most recent snapshot
    snapshots = sorted(SNAPSHOT_DIR.glob("snapshot_*"))
    
    if not snapshots:
        return {
            'success': True,
            'message': 'No snapshots available for comparison'
        }
    
    last_snapshot = snapshots[-1]
    
    changes = {
        'markdown_changes': 0,
        'css_changes': 0,
        'diff_preview': ''
    }
    
    # Compare markdown
    old_md = last_snapshot / "document.md"
    if old_md.exists() and MD_FILE.exists():
        old_lines = old_md.read_text(encoding='utf-8').splitlines()
        new_lines = MD_FILE.read_text(encoding='utf-8').splitlines()
        
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile='previous', tofile='current',
            lineterm='', n=1
        ))
        
        changes['markdown_changes'] = len([d for d in diff if d.startswith('+') or d.startswith('-')])
        
        if diff:
            changes['diff_preview'] += '\n=== MARKDOWN CHANGES ===\n'
            changes['diff_preview'] += '\n'.join(diff[:15])
    
    # Compare CSS
    old_css = last_snapshot / "custom.css"
    if old_css.exists() and CSS_FILE.exists():
        old_lines = old_css.read_text(encoding='utf-8').splitlines()
        new_lines = CSS_FILE.read_text(encoding='utf-8').splitlines()
        
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile='previous', tofile='current',
            lineterm='', n=1
        ))
        
        changes['css_changes'] = len([d for d in diff if d.startswith('+') or d.startswith('-')])
        
        if diff:
            changes['diff_preview'] += '\n\n=== CSS CHANGES ===\n'
            changes['diff_preview'] += '\n'.join(diff[:15])
    
    changes['success'] = True
    return changes


# Bullet list detection helper
_BULLET_RE = re.compile(r'^(\s*)([*+-])\s+.+$')
_HRULE_RE = re.compile(r'^\s*([-*_])(?:\s*\1){2,}\s*$')  # --- , ***, ___ (3+)


def _first_lines_of_bulleted_lists(md: str) -> List[str]:
    """
    Return the full first line (including indentation and bullet symbol)
    for each bulleted list block in the Markdown string `md`.
    Recognizes '-', '*', and '+' as list bullets.
    """
    lines = md.splitlines()
    n = len(lines)
    out: List[str] = []

    def is_bullet(idx: int):
        line = lines[idx]
        if not _BULLET_RE.match(line):
            return False
        # Ignore horizontal rules (---, ***, ___)
        if _HRULE_RE.match(line.strip()):
            return False
        return True

    i = 0
    while i < n:
        if is_bullet(i):
            prev_bullet = is_bullet(i - 1) if i > 0 else False
            prev_blank = (i == 0 or lines[i - 1].strip() == "")
            if not prev_bullet or prev_blank:
                out.append(lines[i])
                # Skip the rest of this list block
                j = i + 1
                while j < n and (is_bullet(j) or lines[j].strip() == "" or lines[j].startswith(" ")):
                    j += 1
                i = j
                continue
        i += 1

    return out


# Agent-callable tool wrappers
@function_tool
def generate_pdf_tool() -> Dict:
    """Generate PDF from current markdown and CSS files.
    
    Call this after making changes to regenerate the PDF.
    """
    return generate_pdf()


@function_tool
def list_changes_tool() -> Dict:
    """Show what changed since last snapshot.
    
    Use this to see the modifications you've made.
    """
    return list_changes()


@function_tool
def get_bulleted_list_first_lines() -> Dict:
    """Find all bulleted lists in the markdown document and return the first line of each.
    
    This is useful for identifying lists that may not have rendered correctly in the PDF.
    Use the returned first lines with insert_blank_line_before() to fix list parsing issues.
    
    Returns:
        {
            'success': bool,
            'first_lines': list[str],  # First line of each bulleted list
            'count': int  # Number of bulleted lists found
        }
    """
    if not MD_FILE.exists():
        return {
            'success': False,
            'error': 'Markdown file not found'
        }
    
    content = MD_FILE.read_text(encoding='utf-8')
    first_lines = _first_lines_of_bulleted_lists(content)
    
    return {
        'success': True,
        'first_lines': first_lines,
        'count': len(first_lines)
    }


if __name__ == "__main__":
    # load docs/x1-basic.md and print first lines of bulleted lists
    # md_path = Path(__file__).parent.parent / "docs" / "x1-basic.md"
    md_path = Path(__file__).parent.parent / "docs" / "x1-premium.md"
    md_content = md_path.read_text(encoding="utf-8")
    lists = _first_lines_of_bulleted_lists(md_content)
    for line in lists:
        print(f'\n{line}')
