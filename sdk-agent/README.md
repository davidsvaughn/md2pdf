# PDF Improvement Agent - OpenAI SDK

An autonomous agent that uses vision analysis and tool calling to improve PDF quality through iterative refinement.

## Overview

This is a rewrite of the ADK-based agent using the **OpenAI Agents SDK**. It demonstrates:
- **True agentic behavior**: Agent directly calls tools using OpenAI's function calling
- **Vision analysis**: Agent analyzes rendered PDF pages using multimodal capabilities
- **Iterative improvement**: Agent makes changes and re-evaluates
- **OpenAI SDK best practices**: Uses `Agent`, `Runner`, and `@function_tool` decorator

## Setup

1. **Install dependencies:**
   ```bash
   cd /home/david/code/x1/md2pdf
   pip install -r sdk-agent/requirements.txt
   ```

2. **Set up environment:**
   ```bash
   cd sdk-agent
   cp .env.example .env
   # Edit .env and add your OPENAI_API_KEY
   ```

## Usage

```bash
cd /home/david/code/x1/md2pdf/sdk-agent
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
   - `get_bulleted_list_first_lines()` - Find all bulleted lists
   - `insert_blank_line_before()` - Fix list parsing
   - `modify_css_property()` - Adjust spacing/pagination
   - `generate_pdf()` - Regenerate PDF
   - `list_changes()` - Verify changes
5. **Iterate**: Repeat until agent approves or max iterations reached

## Tools

The agent has 6 tools at its disposal:

- **read_file(file_type)**: Read markdown or CSS with context
- **get_bulleted_list_first_lines()**: Find all bulleted lists in markdown
- **insert_blank_line_before(file_type, search_text)**: Common fix for list parsing issues
- **modify_css_property(selector, property, value)**: Adjust CSS properties
- **generate_pdf()**: Regenerate PDF from current files
- **list_changes()**: Show diffs since last snapshot

## Output

- **Working files**: `sdk-agent/document.md`, `sdk-agent/custom.css`
- **Final PDF**: `sdk-agent/output.pdf`
- **Snapshots**: `sdk-agent/snapshots/` (automatic backups)

## Architecture

```
sdk-agent/
├── agent.py          # Main agent loop with OpenAI SDK
├── tools.py          # Tool implementations using @function_tool
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

## Migration from ADK

Key differences from the ADK version:

| ADK | OpenAI SDK |
|-----|------------|
| `LlmAgent` | `Agent` |
| `InMemoryRunner` | `Runner` |
| `types.Part.from_bytes()` | Base64 image data URLs |
| `runner.run_async()` event stream | `Runner.run()` returns result |
| `google.genai` | `openai` client built-in |

## Example Session

```
PDF IMPROVEMENT AGENT - OpenAI SDK
============================================================
Model: gpt-4o
Max iterations: 5
============================================================

✓ Agent initialized with tools:
  - read_file
  - get_bulleted_list_first_lines
  - insert_blank_line_before
  - modify_css_property
  - generate_pdf
  - list_changes

============================================================
ITERATION 1/5
============================================================

Generating PDF...
✓ PDF generated: 2 pages
Converting PDF to images...
✓ Converted to 2 images

Sending to agent for analysis...

[Agent Response]: I'll analyze the PDF and fix any issues...

[Tool Call]: get_bulleted_list_first_lines()
[Tool Result]: {'success': True, 'count': 3, 'first_lines': [...]}

[Tool Call]: insert_blank_line_before('markdown', '- Benefits')
[Tool Result]: {'success': True, 'line_number': 42, ...}

[Tool Call]: generate_pdf()
[Tool Result]: {'success': True, 'page_count': 2, ...}

Iteration 1 complete. Continuing...

============================================================
ITERATION 2/5
============================================================

...

✓ AGENT APPROVED PDF QUALITY

Final changes summary:
- Markdown: 3 lines changed
- CSS: 0 lines changed

✓ Final PDF: /home/david/code/x1/md2pdf/sdk-agent/output.pdf
✓ Working files: /home/david/code/x1/md2pdf/sdk-agent
```

## Requirements

- Python 3.8+
- OpenAI API key with access to GPT-4 with vision (gpt-4o or gpt-4-turbo)
- System dependencies for WeasyPrint and pdf2image (see parent project)

## Differences from ADK Implementation

The OpenAI SDK version is more streamlined:

1. **Simpler API**: Direct `Runner.run()` instead of event streaming
2. **Built-in tracing**: OpenAI provides native trace logging
3. **Standard patterns**: Uses widely-adopted OpenAI SDK patterns
4. **Better integration**: Works with broader OpenAI ecosystem
5. **More examples**: Extensive OpenAI SDK documentation and examples

## Troubleshooting

- **Import errors**: Make sure `openai-agents` is installed, not just `openai`
- **Vision errors**: Ensure you're using a vision-capable model (gpt-4o, gpt-4-turbo)
- **API errors**: Check your OpenAI API key has sufficient credits and permissions
- **PDF generation errors**: See parent project's README for system dependencies
