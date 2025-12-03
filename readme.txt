uv venv --python /usr/bin/python3.12
source .venv/bin/activate

uv pip install -r requirements.txt

python md2pdf.py x1-premium.md x1-premium.pdf --theme adwaita-sepia --html-out preview.html

python md2pdf.py x1-basic.md x1-basic.pdf --css css/custom.css

python md2pdf.py x1-premium.md x1-premium.pdf --css css/custom.css
