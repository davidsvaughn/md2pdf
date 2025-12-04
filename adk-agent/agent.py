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
    modify_css_property,
    generate_pdf,
    get_pdf_images,
    save_snapshot,
    list_changes,
    preprocess_broken_lists
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
    """Return agent instructions that tell it to USE tools, not output JSON"""
    return """You are an expert PDF quality improvement agent.

Your task is to analyze rendered PDF pages and FIX any issues you find by calling your available tools.

NOTE: Broken bullet lists have already been fixed in preprocessing. Focus on layout issues.

IMPORTANT: You must CALL TOOLS to make changes. Do NOT output JSON. Call the tools directly.

Available tools:
- read_file(file_type) - Read "markdown" or "css" file contents
- modify_css_property(selector, property, value) - Add/update CSS properties
- generate_pdf() - Regenerate the PDF after making changes
- list_changes() - See what changes you've made

Common issues and how to fix them:

1. PAGE ECONOMY - CRITICAL!
   If the LAST PAGE is less than ~35% filled (mostly blank), you MUST take action:
   
   OPTION A - REDUCE TO FIT:
   - modify_css_property("@page", "margin", "0.5in") to reduce page margins
   - modify_css_property("h1", "margin-top", "0.3em") to reduce heading spacing
   - modify_css_property("h2", "margin-top", "0.3em") to reduce heading spacing
   - modify_css_property("p", "margin-bottom", "0.4em") to reduce paragraph spacing
   
   OPTION B - EXPAND TO FILL:
   - modify_css_property("@page", "margin", "0.75in") to increase margins
   - modify_css_property("p", "margin-bottom", "1em") to increase spacing
   
   *** MARGIN LIMITS: 0.5in minimum, 1in maximum ***

2. BAD PAGE BREAKS:
   - Headings orphaned at bottom of pages
   - Content awkwardly split across pages
   - Use modify_css_property("h2", "page-break-after", "avoid") to keep headings with content

WORKFLOW:
1. Analyze the PDF images - focus on page economy and page breaks
2. Make CSS adjustments to improve layout
3. Call generate_pdf() to regenerate the PDF
4. I will send you updated images for the next iteration

APPROVAL REQUIREMENTS:
- Good page economy (last page >35% filled OR unfixable)
- Clean page breaks (no orphaned headings)
- Margins between 0.4in and 1in

When the PDF meets all requirements, respond with just the word "APPROVED".
"""


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
    
    # =========================================================================
    # PREPROCESSING: Auto-fix broken lists before agent starts
    # =========================================================================
    print("PREPROCESSING: Auto-fixing broken lists...")
    print("-" * 40)
    preprocess_result = preprocess_broken_lists()
    
    if preprocess_result.get('success'):
        print(f"✓ {preprocess_result.get('message')}")
    else:
        print(f"⚠ Preprocessing warning: {preprocess_result.get('message', preprocess_result.get('error'))}")
    
    # Save snapshot after preprocessing
    if preprocess_result.get('fixed_count', 0) > 0:
        save_snapshot(description=f"After preprocessing: fixed {preprocess_result['fixed_count']} broken lists")
    
    print("-" * 40)
    print()
    
    # =========================================================================
    # AGENT SETUP
    # =========================================================================
    
    # Create agent with tools
    agent = LlmAgent(
        name="pdf_improver",
        model=MODEL,
        instruction=instructions,
        description="Expert agent that analyzes PDFs and autonomously fixes quality issues",
        tools=[
            read_file,
            modify_css_property,
            generate_pdf,
            list_changes
        ]
    )
    
    # Create runner
    runner = InMemoryRunner(agent=agent)
    
    # Create session explicitly (async operation)
    session = await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="user"
    )
    
    print("✓ Agent initialized with tools:")
    print("  - read_file")
    print("  - modify_css_property")
    print("  - generate_pdf")
    print("  - list_changes")
    print()
    
    # Main improvement loop
    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n{'='*60}")
        print(f"ITERATION {iteration}/{MAX_ITERATIONS}")
        print(f"{'='*60}\n")
        
        # Generate PDF (skip on first iteration - preprocessing already did it)
        if iteration > 1:
            print("Generating PDF...")
            pdf_result = generate_pdf()
            
            if not pdf_result.get('success'):
                print(f"✗ PDF generation failed: {pdf_result.get('error')}")
                break
            
            print(f"✓ PDF generated: {pdf_result.get('page_count')} pages")
        else:
            print("Using PDF from preprocessing...")
        
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

Here are the current PDF page renders ({len(images)} pages).

1. PAGE ECONOMY: Look at the LAST PAGE (page {len(images)}). If it's less than ~35% filled,
   you MUST reduce margins/spacing to fit content on fewer pages.

2. BAD PAGE BREAKS: Check for orphaned headings or awkward page splits.

CALL THE TOOLS to fix any issues. Do not output JSON - call the tools directly.

After fixing issues, call generate_pdf() to regenerate.

If the PDF meets all requirements (good page economy, clean breaks), respond with "APPROVED".
"""
        
        message_parts = [types.Part.from_text(text=prompt_text)]
        
        # Add images
        for idx, img_bytes in enumerate(images):
            message_parts.append(
                types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg')
            )
        
        content = types.UserContent(parts=message_parts)
        
        # Run agent with multimodal input
        print("\nSending to agent for analysis...\n")
        
        # Use async runner.run_async() per ADK samples
        events_list = []
        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=content
        ):
            events_list.append(event)
            # Print agent responses and tool calls in real-time
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(f"[Agent]: {part.text}")
                    # Check for function calls
                    if hasattr(part, 'function_call') and part.function_call:
                        print(f"[Tool Call]: {part.function_call.name}({part.function_call.args})")
                    # Check for function responses
                    if hasattr(part, 'function_response') and part.function_response:
                        print(f"[Tool Result]: {part.function_response.name} -> {str(part.function_response.response)[:200]}")
        
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
    parser.add_argument('--source', 
                        # default='x1-basic', 
                        # default='x1-premium', 
                        # default='ath-premium', 
                        default='art-premium', 
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
