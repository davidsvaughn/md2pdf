Pipeline to convert Markdown to PDF with the same styling Apostrophe uses in its preview. CSS and Lua filters are vendored locally so the script runs standalone.

What it does
- Uses the CSS themes in `css/` (copied from Apostrophe: Adwaita light/dark, sepia, high contrast).
- Runs Pandoc with the same Lua filters as the preview (`relative_to_absolute.lua`, `task-list.lua`) and MathJax enabled.
- Converts the generated HTML to PDF with wkhtmltopdf (so the CSS is applied).

Prerequisites
- Python 3.8+
- Pandoc in `PATH`
- wkhtmltopdf in `PATH`
- Fira Sans/Mono fonts installed for a closer match (or swap fonts in the CSS)

Usage
```
python md2pdf.py INPUT.md OUTPUT.pdf \
  [--theme adwaita|adwaita-sepia|highcontrast|highcontrast_inverse] \
  [--css /absolute/path/to/custom.css] \
  [--html-out preview.html] \
  [--no-mathjax]
```

Notes
- Everything needed lives under this folder; no files are read from the rest of the repo.
- By default, the pipeline uses `css/adwaita.css`. Other themes map to the other CSS files in that folder.
- If you set `--css`, that path is passed directly to Pandoc and overrides the theme choice.
- `--html-out` lets you keep the intermediate HTML for debugging; otherwise it is written to a temp file and removed.
- The Lua filters live in `lua/` and are applied automatically.
- wkhtmltopdf is invoked with `--enable-local-file-access` so local CSS works; if you still see blocked CSS, ensure you are using this script version.
