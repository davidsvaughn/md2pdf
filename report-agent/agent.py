"""
ADK-based PDF improvement agent.
Uses vision analysis and autonomous tool calling to improve PDF quality.
"""

import os
import sys
import asyncio
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

# Import our tools
from tools import (
    read_file,
    insert_blank_line_before,
    modify_css_property,
    generate_pdf,
    get_pdf_images,
    save_snapshot,
    list_changes
)

load_dotenv()

# Configuration
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "5"))
# MODEL = "gemini-2.5-flash"
MODEL = "gemini-2.5-pro"

# Paths
WORK_DIR = Path(__file__).parent
DOCS_DIR = WORK_DIR.parent / "docs"
PROMPTS_DIR = WORK_DIR.parent / "prompts"

def load_instructions() -> str:
    """Load agent instructions from p4.md"""
    instructions_file = PROMPTS_DIR / "p4.md"
    
    if not instructions_file.exists():
        return """You are an expert PDF quality improvement agent.
        
Your task is to analyze rendered PDF pages and use your available tools to fix any issues.

Common issues and fixes:
- Lists appearing as inline text with dashes → Use insert_blank_line_before() to add space before the list
- Poor spacing/pagination → Use modify_css_property() to adjust margins/padding
- Text overflow or cut-off → Adjust CSS properties

When you're satisfied with the quality, respond with "APPROVED" to end the process.
"""
    
    return instructions_file.read_text(encoding='utf-8')


def setup_working_directory(source_name: str = "x1-basic"):
    """Copy source files from docs/ to working directory"""
    
    # Determine source files
    source_md = DOCS_DIR / f"{source_name}.md"
    source_css = DOCS_DIR / "custom.css"
    
    target_md = WORK_DIR / "document.md"
    target_css = WORK_DIR / "custom.css"
    
    if not source_md.exists():
        print(f"Error: Source markdown not found: {source_md}")
        sys.exit(1)
    
    if not source_css.exists():
        print(f"Error: Source CSS not found: {source_css}")
        sys.exit(1)
    
    # Copy files
    shutil.copy2(source_md, target_md)
    shutil.copy2(source_css, target_css)
    
    print(f"✓ Copied {source_name}.md and custom.css to working directory")
    
    # Create initial snapshot
    save_snapshot(description="Initial state")
    print("✓ Created initial snapshot")


async def improve_pdf():
    """Main agent loop for PDF improvement"""
    
    # Validate API key
    if not GOOGLE_API_KEY:
        print("Error: GOOGLE_API_KEY not found in environment")
        print("Please create a .env file with your API key")
        sys.exit(1)
    
    # Load instructions
    instructions = load_instructions()
    
    print(f"\n{'='*60}")
    print(f"PDF IMPROVEMENT AGENT - ADK POC")
    print(f"{'='*60}")
    print(f"Model: {MODEL}")
    print(f"Max iterations: {MAX_ITERATIONS}")
    print(f"{'='*60}\n")
    
    # Create agent with tools
    agent = LlmAgent(
        name="pdf_improver",
        model=MODEL,
        instruction=instructions,
        description="Expert agent that analyzes PDFs and autonomously fixes quality issues",
        tools=[
            read_file,
            insert_blank_line_before,
            modify_css_property,
            generate_pdf,
            list_changes
        ]
    )
    
    # Create runner
    runner = InMemoryRunner(agent=agent)
    
    # Create session explicitly (required for run_async)
    session = runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="user"
    )
    
    print("✓ Agent initialized with tools:")
    print("  - read_file")
    print("  - insert_blank_line_before")
    print("  - modify_css_property")
    print("  - generate_pdf")
    print("  - list_changes")
    print()
    
    # Main improvement loop
    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n{'='*60}")
        print(f"ITERATION {iteration}/{MAX_ITERATIONS}")
        print(f"{'='*60}\n")
        
        # Generate PDF
        print("Generating PDF...")
        pdf_result = generate_pdf()
        
        if not pdf_result.get('success'):
            print(f"✗ PDF generation failed: {pdf_result.get('error')}")
            break
        
        print(f"✓ PDF generated: {pdf_result.get('page_count')} pages")
        
        # Get PDF images for vision analysis
        print("Converting PDF to images...")
        images = get_pdf_images()
        
        if not images:
            print("✗ Failed to convert PDF to images")
            break
        
        print(f"✓ Converted to {len(images)} images")
        
        # Read current files for context
        md_content = read_file("markdown")
        css_content = read_file("css")
        
        # Build multimodal message
        prompt_text = f"""
ITERATION {iteration} OF {MAX_ITERATIONS}

Analyze the PDF page renders below and determine if quality is acceptable.

You have access to these tools:
- read_file(file_type) - Read markdown or CSS content
- insert_blank_line_before(file_type, search_text) - Add blank line (common fix for list parsing)
- modify_css_property(selector, property, value) - Adjust CSS for spacing/pagination
- generate_pdf() - Regenerate PDF after changes
- list_changes() - See what you've modified

CURRENT FILES:
- Markdown: {md_content.get('line_count', 0)} lines
- CSS: {css_content.get('line_count', 0)} lines

CRITICAL: Check for broken lists (items appearing as inline text with dashes instead of vertical bullets).

When satisfied with quality, respond with "APPROVED" to end the process.
"""
        
        message_parts = [types.Part.from_text(text=prompt_text)]
        
        # Add images
        for idx, img_bytes in enumerate(images):
            message_parts.append(
                types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg')
            )
        
        content = types.Content(role='user', parts=message_parts)
        
        # Run agent with multimodal input
        print("\nSending to agent for analysis...\n")
        
        # Use run_async for multimodal content (run_debug only supports strings)
        events_list = []
        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=content
        ):
            events_list.append(event)
            # Print agent responses in real-time
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(f"[Agent]: {part.text}")
        
        events = events_list
        
        # Check for approval in agent response
        approved = False
        if events:
            for event in events:
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text and 'APPROVED' in part.text.upper():
                            approved = True
                            break
        
        if approved:
            print(f"\n{'='*60}")
            print("✓ AGENT APPROVED PDF QUALITY")
            print(f"{'='*60}\n")
            break
        
        # Continue to next iteration
        print(f"\nIteration {iteration} complete. Continuing...\n")
    
    else:
        # Loop completed without approval
        print(f"\n{'='*60}")
        print(f"Reached maximum iterations ({MAX_ITERATIONS})")
        print(f"{'='*60}\n")
    
    # Show final changes
    print("\nFinal changes summary:")
    changes = list_changes()
    if changes.get('success'):
        print(f"- Markdown: {changes.get('markdown_changes', 0)} lines changed")
        print(f"- CSS: {changes.get('css_changes', 0)} lines changed")
        if changes.get('diff_preview'):
            print("\nDiff preview:")
            print(changes['diff_preview'])
    
    print(f"\n✓ Final PDF: {WORK_DIR / 'output.pdf'}")
    print(f"✓ Working files: {WORK_DIR}\n")


def main():
    """Entry point"""
    
    # Parse command line
    import argparse
    parser = argparse.ArgumentParser(description='ADK-based PDF improvement agent')
    parser.add_argument('--source', default='x1-basic', 
                       help='Source markdown name (without .md extension)')
    args = parser.parse_args()
    
    # Setup working directory
    setup_working_directory(args.source)
    
    # Run agent
    try:
        asyncio.run(improve_pdf())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
