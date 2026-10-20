"""Visual QA contact sheets from rendered selected PDF pages (bundled Python)."""
import json
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
batch = json.loads((ROOT / 'reports/company-evidence-batch.json').read_text())
for item in batch['companies']:
    if item['status'] != 'prepared':
        continue
    root = ROOT / 'company-packs' / item['company']
    manifest = json.loads((root / 'manifest.json').read_text())
    pages = json.loads((root / manifest['pages']).read_text(encoding='utf-8'))
    sample = sorted({0, len(pages)//2, len(pages)-1})
    canvas = Image.new('RGB',(1500,850),'#e9eef3')
    draw = ImageDraw.Draw(canvas)
    for col, n in enumerate(sample):
        image = Image.open(root / pages[n]['screenshot']).convert('RGB')
        image.thumbnail((480,785))
        x = col * 500 + (500-image.width)//2
        y = 45
        canvas.paste(image,(x,y))
        draw.text((col*500+12,12), f'{item["company"]}: pack page {n+1}, original {pages[n]["original_page"]}', fill='#142c43')
    output = ROOT / 'tmp/pdfs' / (item['company'] + '-evidence-review.png')
    canvas.save(output)
    print(output)
