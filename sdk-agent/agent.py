"""
OpenAI Agents SDK-based PDF improvement agent.
Uses vision analysis and autonomous tool calling to improve PDF quality.
"""

import os
import sys
import asyncio
import shutil
import base64
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import Agent, Runner, ItemHelpers, ModelSettings
from openai.types.shared import Reasoning

# Import our tools
# Functions decorated with @function_tool are for the agent to call
# Plain functions are for direct orchestration code use
from tools import (
    # Agent tools (decorated with @function_tool)
    read_file,
    insert_page_break_before,
    insert_vertical_space_before,
    modify_css_property,
    generate_pdf_tool,
    list_changes_tool,
    # Direct call functions (not decorated)
    generate_pdf,
    get_pdf_images,
    save_snapshot,
    list_changes,
    preprocess_broken_lists,  # Auto-fix broken lists before agent starts
)

load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "5"))
MODEL = os.getenv("MODEL", "gpt-4o")  # Vision-capable model
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "medium")  # minimal, low, medium, high

# Paths
WORK_DIR = Path(__file__).parent
DOCS_DIR = WORK_DIR.parent / "docs"
PROMPTS_DIR = WORK_DIR.parent / "prompts"


def load_instructions() -> str:
    """Return agent instructions that tell it to USE tools, not output JSON"""
    return """You are an expert PDF quality improvement agent.

Your task is to analyze rendered PDF pages and FIX any formatting issues by calling your available tools.

NOTE: Broken bullet lists have already been fixed in preprocessing. Focus on layout issues.

IMPORTANT: You must CALL TOOLS to make changes. Do NOT output JSON. Call the tools directly.

Available tools:
- read_file(file_type) - Read "markdown" or "css" file contents
- insert_page_break_before(search_text) - Force a page break before content
- insert_vertical_space_before(search_text, amount) - Add vertical space before content
- modify_css_property(selector, property, value) - Add/update CSS properties
- generate_pdf_tool() - Regenerate the PDF after making changes
- list_changes_tool() - See what changes you've made

==========================================================================
ISSUE 1: PAGE ECONOMY - CRITICAL!
==========================================================================

RULE: If the LAST PAGE is less than ~35% filled (more than 65% blank),
you MUST take action to improve page economy.

OPTION A - REDUCE TO FIT:
- modify_css_property("h1", "margin-top", "0.3em")
- modify_css_property("h2", "margin-top", "0.3em") 
- modify_css_property("p", "margin-bottom", "0.4em")
- modify_css_property("@page", "margin", "0.5in") - NOT below 0.4in!

OPTION B - EXPAND TO FILL:
- modify_css_property("@page", "margin", "0.75in")
- modify_css_property("p", "margin-bottom", "1em")

*** MARGIN LIMITS: 0.4in minimum, 1in maximum ***

==========================================================================
ISSUE 2: BAD PAGE BREAKS
==========================================================================

Fix awkward breaks with:
- insert_page_break_before(search_text)
- insert_vertical_space_before(search_text, amount)
- modify_css_property("h2", "page-break-after", "avoid")

==========================================================================
APPROVAL REQUIREMENTS - ALL MUST BE TRUE:
==========================================================================

1. Good page economy (last page >35% filled OR unfixable)
2. Clean page breaks (no orphaned headings, no split content)
3. Margins between 0.4in and 1in

Only respond with "APPROVED" when ALL requirements are met.
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
    if not OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not found in environment")
        print("Please create a .env file with your API key")
        sys.exit(1)
    
    # Load instructions
    instructions = load_instructions()
    
    print(f"\n{'='*60}")
    print(f"PDF IMPROVEMENT AGENT - OpenAI SDK")
    print(f"{'='*60}")
    print(f"Model: {MODEL}")
    print(f"Reasoning effort: {REASONING_EFFORT}")
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
    
    # Create agent with tools and reasoning settings
    agent = Agent(
        name="pdf_improver",
        model=MODEL,
        instructions=instructions,
        model_settings=ModelSettings(
            reasoning=Reasoning(effort=REASONING_EFFORT),
        ),
        tools=[
            read_file,
            insert_page_break_before,
            insert_vertical_space_before,
            modify_css_property,
            generate_pdf_tool,
            list_changes_tool
        ]
    )
    
    print("✓ Agent initialized with tools:")
    print("  - read_file")
    print("  - insert_page_break_before")
    print("  - insert_vertical_space_before")
    print("  - modify_css_property")
    print("  - generate_pdf_tool")
    print("  - list_changes_tool")
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
        
        # Build multimodal message for OpenAI Agents SDK
        # The SDK uses specific content types: 'input_text' and 'input_image'
        # input_image uses 'image_url' field with data URL or https URL
        prompt_text = f"""
ITERATION {iteration} OF {MAX_ITERATIONS}

Here are the current PDF page images ({len(images)} pages). 

NOTE: Broken bullet lists have already been fixed. Focus on layout issues:

1. PAGE ECONOMY: Look at the LAST PAGE (page {len(images)}). If it's less than ~35% filled 
   (mostly blank), you MUST reduce margins/spacing to fit content on fewer pages.
   
2. BAD PAGE BREAKS: Headings orphaned at bottom of pages, split content, etc.

Fix any issues you find, then call generate_pdf_tool() to see the results.

If everything looks good (good page economy, clean breaks), respond with "APPROVED".
"""
        
        # Create content parts array with text and images
        content_parts = [{"type": "input_text", "text": prompt_text}]
        
        for idx, img_bytes in enumerate(images):
            # Convert to base64 data URL for OpenAI Agents SDK
            b64_img = base64.b64encode(img_bytes).decode('utf-8')
            content_parts.append({
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{b64_img}",
                "detail": "high"
            })
        
        # Wrap in proper message format
        user_message = {
            "role": "user",
            "content": content_parts
        }
        
        # Run agent with multimodal input
        print("\nSending to agent for analysis...\n")
        
        try:
            # Use Runner.run with the properly formatted message
            result = await Runner.run(
                agent,
                input=[user_message]  # Pass as a list of messages
            )
            
            # Print all items from the run to see the agent's reasoning
            print("\n" + "="*60)
            print("AGENT REASONING AND ACTIONS:")
            print("="*60)
            for item in result.new_items:
                if item.type == "reasoning_item":
                    # Extended thinking / reasoning (from reasoning=high setting)
                    if hasattr(item, 'summary') and item.summary:
                        print(f"\n[REASONING SUMMARY]:\n{item.summary}")
                    if hasattr(item, 'raw_item'):
                        for part in getattr(item.raw_item, 'summary', []):
                            if hasattr(part, 'text'):
                                print(f"\n[REASONING]:\n{part.text}")
                elif item.type == "message_output_item":
                    # Agent's text messages (reasoning)
                    text = ItemHelpers.text_message_output(item)
                    print(f"\n[AGENT MESSAGE]:\n{text}")
                elif item.type == "tool_call_item":
                    # Tool being called
                    print(f"\n[TOOL CALL]: {item.raw_item.name}({item.raw_item.arguments})")
                elif item.type == "tool_call_output_item":
                    # Tool result (truncate if too long)
                    output = str(item.output)
                    if len(output) > 500:
                        output = output[:500] + "..."
                    print(f"[TOOL RESULT]: {output}")
            print("="*60 + "\n")
            
            # Print agent's final response
            print(f"[Final Output]: {result.final_output}\n")
            
            # Check for approval
            if 'APPROVED' in result.final_output.upper():
                print(f"\n{'='*60}")
                print("✓ AGENT APPROVED PDF QUALITY")
                print(f"{'='*60}\n")
                break
            
        except Exception as e:
            print(f"Error running agent: {e}")
            import traceback
            traceback.print_exc()
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
    parser = argparse.ArgumentParser(description='OpenAI SDK-based PDF improvement agent')
    parser.add_argument('--source', 
                        # default='x1-basic',
                        # default='x1-premium',
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
