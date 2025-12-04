# PDF Improvement Agent - ADK POC

An autonomous agent that uses vision analysis and tool calling to improve PDF quality through iterative refinement.

## Overview

This proof-of-concept demonstrates:
- **True agentic behavior**: Agent directly calls tools (no JSON parsing)
- **Vision analysis**: Agent analyzes rendered PDF pages
- **Iterative improvement**: Agent makes changes and re-evaluates
- **ADK best practices**: Uses `InMemoryRunner` with multimodal inputs

## Setup

1. **Install dependencies:**
   ```bash
   cd /home/david/code/x1/md2pdf
   uv pip install -r adk-agent/requirements.txt
   ```

2. **Set up environment:**
   ```bash
   cd adk-agent
   cp .env.example .env
   # Edit .env and add your GOOGLE_API_KEY
   ```

## Usage

```bash
cd /home/david/code/x1/md2pdf/adk-agent
python agent.py --source x1-basic
```

Options:
- `--source`: Source markdown name (default: `x1-basic`)
  - Available: `x1-basic`, `x1-premium`, `ath-basic`, `ath-premium`

## How It Works

1. **Setup**: Copies source files to working directory
2. **Generate**: Creates initial PDF
3. **Analyze**: Converts PDF to images, sends to vision model
4. **Act**: Agent autonomously calls tools to fix issues:
   - `read_file()` - Read markdown/CSS
   - `insert_blank_line_before()` - Fix list parsing
   - `modify_css_property()` - Adjust spacing/pagination
   - `generate_pdf()` - Regenerate PDF
   - `list_changes()` - Verify changes
5. **Iterate**: Repeat until agent approves or max iterations reached

## Tools

The agent has 5 tools at its disposal:

- **read_file(file_type)**: Read markdown or CSS with context
- **insert_blank_line_before(file_type, search_text)**: Common fix for list parsing issues
- **modify_css_property(selector, property, value)**: Adjust CSS properties
- **generate_pdf()**: Regenerate PDF from current files
- **list_changes()**: Show diffs since last snapshot

## Output

- **Working files**: `adk-agent/document.md`, `adk-agent/custom.css`
- **Final PDF**: `adk-agent/output.pdf`
- **Snapshots**: `adk-agent/snapshots/` (automatic backups)

## Architecture

```
adk-agent/
├── agent.py          # Main agent loop with ADK
├── tools.py          # Tool implementations
├── requirements.txt  # Dependencies
├── .env.example      # Environment template
└── snapshots/        # Automatic backups (created at runtime)
```

## Key Features

- **Automatic snapshots**: State saved before each modification
- **Fuzzy search**: Tools use case-insensitive matching
- **Rich feedback**: Tools return detailed context for agent learning
- **Multimodal**: Agent sees both PDF renders and source files
- **Safety**: Max iterations limit prevents runaway execution

## Example Session

```
PDF IMPROVEMENT AGENT - ADK POC
============================================================
Model: gemini-2.0-flash-exp
Max iterations: 5
============================================================

✓ Agent initialized with tools:
  - read_file
  - insert_blank_line_before
  - modify_css_property
  - generate_pdf
  - list_changes

============================================================
ITERATION 1/5
============================================================

Generating PDF...
✓ PDF generated: 3 pages
Converting PDF to images...
✓ Converted to 3 images

Sending to agent for analysis...

[Agent analyzes images, calls tools autonomously...]

✓ AGENT APPROVED PDF QUALITY
```
