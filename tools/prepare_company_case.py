"""Preserve page-addressable text from an explicitly supplied local company corpus."""
import argparse
import hashlib
import json
from pathlib import Path
from pypdf import PdfReader
from backend import library, storage

def prepare(company):
    root = library.root_folder()
    target = storage.PROJECT_DIR / 'outputs' / f'{company}-source-review'
    target.mkdir(parents=True, exist_ok=True)
    entries = []
    for file in sorted((root/company).rglob('*')):
        if not file.is_file() or file.suffix.lower() != '.pdf':
            continue
        if not file.resolve().is_relative_to(root):
            continue
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        result = target / (digest[:16]+'.json')
        if result.exists():
            document = json.loads(result.read_text(encoding='utf-8'))
        else:
            reader = PdfReader(file)
            document = {'file':file.relative_to(root).as_posix(), 'sha256':digest,
                        'metadata':{str(k):str(v) for k,v in (reader.metadata or {}).items()},
                        'pages':[{'pdf_page':i+1,'text':page.extract_text() or ''} for i,page in enumerate(reader.pages)]}
            result.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
            text = '\n\n'.join(f'=== PDF PAGE {p["pdf_page"]} ===\n{p["text"]}' for p in document['pages'])
            result.with_suffix('.txt').write_text(text, encoding='utf-8')
        entries.append({'source_file':document['file'], 'sha256':digest, 'pages':len(document['pages']),
                        'extracted_file':str(result.relative_to(storage.PROJECT_DIR))})
        print(json.dumps(entries[-1]), flush=True)
    (target/'inventory.json').write_text(json.dumps(entries,indent=2), encoding='utf-8')

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('company')
    prepare(parser.parse_args().company)
