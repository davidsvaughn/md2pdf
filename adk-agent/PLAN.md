# ADK-Based PDF Generation Agent - Implementation Plan

## Overview

Transform the existing `agent_v1.py` into a true agentic system using Google's Agent Development Kit (ADK). Instead of manually orchestrating LLM calls and parsing JSON responses, we'll build an agent that autonomously uses tools to iteratively improve PDF quality through vision analysis and targeted file modifications.

## Core Philosophy - **POC FOCUS**

**This is a Proof of Concept** - Focus on core functionality that proves the agentic approach works. Skip bells/whistles/fallbacks that would be needed for production.

**True Autonomy**: The agent observes PDF renders, reasons about quality issues, and directly calls tools to fix problems. No manual JSON parsing or hardcoded action interpretation—the agent learns and adapts through tool feedback.

**Simplicity**: Clean, focused tools that do one thing well. The agent composes these primitives into complex workflows through its own reasoning.

**ADK Best Practices**: Follow patterns from official ADK documentation - use `InMemoryRunner` with `run_debug()` for quick iteration, leverage `types.Part.from_bytes()` for images, use simple function-based tools.

## Architecture

### 1. Agent Configuration (Simple POC)
- **Model**: `gemini-2.0-flash-exp` (vision + tool calling)
- **Instructions**: Load from `../prompts/p4.md` (existing quality criteria)
- **Runner**: ADK's `InMemoryRunner` for simplicity (no persistence needed for POC)
- **Execution**: Use `run_debug()` helper for streamlined interaction

### 2. Tool Design Philosophy (POC-Focused)

Simple Python functions with ADK type hints. Tools return dicts with rich feedback. For POC, focus on the most commonly needed operations.

#### Essential File Tools (POC Set)
```python
def read_file(file_type: str) -> dict:
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

def insert_blank_line_before(file_type: str, search_text: str) -> dict:
    """Insert blank line before first occurrence.
    Common fix for markdown list parsing issues.
    
    Args:
        file_type: "markdown" or "css"
        search_text: Text to search for (fuzzy matching)
    
    Returns:
        {
            'success': bool,
            'line_number': int,
            'context': str  # 3 lines before/after
        }
    """

def modify_css_property(selector: str, property: str, value: str) -> dict:
    """Add or update CSS property for a selector.
    
    Args:
        selector: CSS selector (e.g., "@page", "h2")
        property: CSS property name (e.g., "margin-top")
        value: New value (e.g., "0.5em")
    
    Returns:
        {
            'success': bool,
            'action': 'added' | 'updated',
            'full_rule': str  # the complete CSS rule
        }
    """
```

#### PDF Tools (POC Set)
```python
def generate_pdf() -> dict:
    """Generate PDF from current markdown and CSS.
    
    Returns:
        {
            'success': bool,
            'pdf_path': str,
            'page_count': int,
            'error': str | None
        }
    """

def get_pdf_images() -> list[bytes]:
    """Convert PDF pages to JPEG bytes for vision analysis.
    Returns list of image bytes (1024x1024 JPEG).
    """
```

#### State Tools (POC Set - Minimal)
```python
def save_snapshot(description: str = "") -> dict:
    """Save current state (auto-called before edits).
    
    Returns:
        {
            'snapshot_id': str,
            'timestamp': str
        }
    """

def list_changes() -> dict:
    """Show what changed since last snapshot.
    
    Returns:
        {
            'markdown_changes': int,  # lines changed
            'css_changes': int,
            'diff_preview': str  # first 10 changes
        }
    """
```

## Workflow (POC Pattern - ADK Best Practices)

### Initialization
1. Load API key from environment
2. Create `Agent` with Gemini model, tools, and instructions
3. Create `InMemoryRunner` with the agent
4. Copy source files from `docs/` to working directory
5. Initial snapshot

### Main Loop (Using ADK `run_debug` Pattern)
```python
from google.adk import Agent, InMemoryRunner
from google.genai import types
import asyncio

# Setup
agent = Agent(
    name="pdf_improver",
    model="gemini-2.0-flash-exp",
    instruction=load_instructions(),
    tools=[read_file, insert_blank_line_before, modify_css_property, 
           generate_pdf, get_pdf_images, save_snapshot, list_changes]
)

runner = InMemoryRunner(agent=agent, app_name="pdf_agent")

async def improve_pdf(max_iterations: int = 5):
    for iteration in range(max_iterations):
        # Generate PDF and get images
        pdf_result = generate_pdf()
        if not pdf_result['success']:
            print(f"PDF generation failed: {pdf_result['error']}")
            break
            
        # Get images as bytes
        images = get_pdf_images()
        
        # Create multimodal message using ADK pattern
        message_parts = [
            types.Part.from_text(f"""
Iteration {iteration + 1} of {max_iterations}

Analyze these PDF page renders and determine if quality is acceptable.
If issues exist, use available tools to fix them:
- insert_blank_line_before() for list parsing issues
- modify_css_property() for spacing/pagination
- read_file() to understand structure
- list_changes() to verify your edits

When satisfied with quality, respond with "APPROVED" to end the process.
""")
        ]
        
        # Add images using ADK best practice
        for img_bytes in images:
            message_parts.append(
                types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg')
            )
        
        content = types.Content(role='user', parts=message_parts)
        
        # Use run_debug for clean execution (ADK recommended pattern)
        events = await runner.run_debug(
            content,
            quiet=False,  # Show agent reasoning
            verbose=True  # Show tool calls
        )
        
        # Check for approval in agent response
        last_event = events[-1] if events else None
        if last_event and last_event.content:
            response_text = ''.join(
                p.text for p in last_event.content.parts if p.text
            )
            if 'APPROVED' in response_text:
                print("✓ Agent approved PDF quality")
                break
    
    print(f"Completed after {iteration + 1} iterations")

# Run
asyncio.run(improve_pdf())
```

## Key Improvements Over v1

### 1. **True Tool Calling**
- Old: Agent returns JSON, we parse and execute
- New: Agent directly calls tools, receives feedback, adapts

### 2. **Better Edit Tools**
- Old: `replace_in_file(original, replacement)` - fragile exact match
- New: Context-aware tools (insert blank lines, modify CSS properties, section-based edits)

### 3. **Agent Learning**
- Old: Single-shot planning (agent sees images once, suggests all fixes)
- New: Iterative feedback loop (agent tries fix → sees result → adjusts strategy)

### 4. **Simpler State Management**
- Old: Manual snapshot/rollback in Python
- New: ADK's session management + explicit snapshot tools

### 5. **Richer Tool Feedback**
- Old: Tools just execute silently
- New: Tools return context (line numbers, diffs, verification snippets)

## File Structure (POC - Minimal)

```
adk-agent/
├── tools.py          # All tool implementations
├── agent.py          # Agent setup and main loop
├── requirements.txt  # Dependencies
├── .env.example      # Environment template
└── PLAN.md          # This file
```

## Implementation Order (POC)

1. **tools.py** - Implement essential tools (6 functions)
2. **agent.py** - Main script with agent + execution loop
3. **requirements.txt** & **.env.example** - Setup files

## Dependencies (POC-Minimal)

```
google-genai>=1.0.0    # ADK included
pdf2image              # PDF → images
Pillow                 # Image processing
python-dotenv          # Environment config
```

Note: No LiteLLM or other fallback models for POC.

## Configuration (POC)

```bash
# .env
GOOGLE_API_KEY=xxx              # For Gemini models
MAX_ITERATIONS=5                # Safety limit
```

## Success Criteria (POC)

1. **Agent autonomy**: Agent directly calls tools (no manual JSON parsing)
2. **Vision integration**: Agent analyzes PDF renders using multimodal input
3. **Iterative improvement**: Agent can make multiple refinements per run
4. **Quality result**: Produces PDFs comparable to or better than v1

## Key Simplifications for POC

- No fallback models (Gemini only)
- No complex snapshot/rollback (simple save before edit)
- No extensive validation/error handling
- No CLI arguments (hardcoded defaults)
- No detailed logging/observability
- Use `InMemoryRunner` + `run_debug()` (ADK recommended pattern for development)
- Tools return simple dicts, not complex objects

## Next Steps (POC Implementation)

1. Implement `tools.py` - 6 essential functions
2. Implement `agent.py` - Main execution loop with ADK patterns
3. Test with one markdown file
4. Iterate based on results

**Ready to build!** This POC proves the agentic approach works without production complexity.
