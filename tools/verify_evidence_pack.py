"""Read-back checks of the published company pack; no model calls or PDF authoring."""
import argparse
import json
from pypdf import PdfReader
from backend import storage, evidence_packs as packs, library

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('company')
    args = parser.parse_args()
    manifest = packs.read_manifest(args.company)
    root = packs.pack_root(args.company)
    index = json.loads((root / manifest['pages']).read_text(encoding='utf-8'))
    reader = PdfReader(root / manifest['pdf'])
    assert len(reader.pages) == len(index) == manifest['selected_pages']
    assert packs._valid_artifacts(root, manifest['artifact_hashes'])
    lookup = {(p['source_file'], p['original_page']) for p in index}
    for record in library.company_records(args.company):
        if record.review_status in ('source_verified', 'user_verified') and record.source_sha256:
            assert all((record.source_file, page) in lookup for page in packs._int_pages(record.source_page))
    # Check page order and copied PDF content at the beginning, middle and end.
    for number in (0, len(index)//2, len(index)-1):
        actual = ' '.join((reader.pages[number].extract_text(extraction_mode='layout') or '').split())
        expected = ' '.join(index[number]['text'].split())
        assert actual == expected, f'Copied evidence content mismatch on pack page {number+1}'
    repeated = packs.refresh(args.company)
    assert repeated['reused'] and not repeated['page_renders'] and not repeated['pdf_text_extractions']
    print(json.dumps({'company': args.company, 'selected_pages': len(index),
        'all_reviewed_source_pages_included': True, 'published_artifacts_hash_verified': True,
        'sample_pdf_content_and_order_verified': True, 'repeat_seconds': repeated['elapsed_seconds'],
        'active_research': storage.rows('SELECT id,status FROM research_runs WHERE status IN (?,?)', ('queued','running')),
        'active_exports': storage.rows('SELECT id,status FROM excel_exports WHERE status IN (?,?)', ('queued','building'))}, indent=2))
