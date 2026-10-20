"""Re-extract unreviewed annual PDFs after adding their missing font decoder."""
import json
import argparse
from pypdf.errors import LimitReachedError
from backend import storage, documents, library, evidence_packs as packs

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--company', default='itc')
    args = parser.parse_args()
    rows = storage.rows('SELECT d.id,d.local_path,d.sha256,COUNT(p.id) AS pages FROM documents d JOIN passages p ON p.document_id=d.id WHERE d.company=? GROUP BY d.id HAVING COUNT(p.id)>80', (args.company,))
    for row in rows:
        # Do not change text underlying any accepted/pending financial fact.
        used = storage.rows('SELECT COUNT(*) AS n FROM facts f JOIN passages p ON p.id=f.passage_id WHERE p.document_id=?', (row['id'],))[0]['n']
        if used:
            raise ValueError('Source already supports financial facts; manual migration required.')
        path = storage.PROJECT_DIR / row['local_path']
        assert packs.digest_file(path) == row['sha256']
        method = 'pypdf-layout'
        try:
            pages, _ = documents.extract(path.read_bytes(), 'application/pdf')
        except LimitReachedError:
            pages = library.extract_local_pdf_fallback(path)
            method = 'local-bounded-fallback'
        with storage.database() as db:
            for n, text in enumerate(pages, 1):
                db.execute('INSERT INTO passages(document_id,pdf_page,text) VALUES(?,?,?) ON CONFLICT(document_id,pdf_page) DO UPDATE SET text=excluded.text',
                           (row['id'],n,text))
        processed = storage.DATA_DIR / 'processed' / (row['sha256'] + '.json')
        processed.write_text(json.dumps({'sha256':row['sha256'], 'pages':pages, 'font_decoder':'fonttools-4.67.0', 'extraction_method':method}, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'annual_report':str(path.name), 'reextracted_pages':len(pages)}), flush=True)
