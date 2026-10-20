"""Verify every copied page stream and metadata before publishing company packs."""
import json
from pathlib import Path
from pypdf import PdfReader
from backend import storage, evidence_packs as packs, library

if __name__ == '__main__':
    batch = json.loads((storage.PROJECT_DIR / 'reports/company-evidence-batch.json').read_text())
    results = []
    for item in batch['companies']:
        if item['status'] == 'empty':
            results.append({'company':item['company'], 'status':'no_original_files'})
            continue
        assert item['status'] == 'prepared', item
        company = item['company']
        manifest = packs.read_manifest(company)
        root = packs.pack_root(company)
        assert manifest['signature'] == item['signature']
        assert packs.source_fingerprints(company) == manifest['source_fingerprints']
        assert packs._valid_artifacts(root, manifest['artifact_hashes'])
        index = json.loads((root / manifest['pages']).read_text(encoding='utf-8'))
        copied = PdfReader(root / manifest['pdf'])
        assert len(copied.pages) == len(index) == manifest['selected_pages']
        originals = {}
        for number, page in enumerate(index):
            sha = page['source_sha256']
            assert manifest['source_fingerprints'][page['source_file']] == sha
            if sha not in originals:
                originals[sha] = PdfReader(storage.DATA_DIR / 'raw' / (sha + '.pdf'))
            original = originals[sha].pages[page['original_page']-1]
            actual = copied.pages[number]
            assert actual.get_contents().get_data() == original.get_contents().get_data(), (company,number+1)
            assert list(actual.mediabox) == list(original.mediabox), (company,number+1,'dimensions')
            assert list(actual.cropbox) == list(original.cropbox), (company,number+1,'crop')
            assert actual.get('/Rotate',0) == original.get('/Rotate',0), (company,number+1,'rotation')
        selected = {(p['source_file'],p['original_page']) for p in index}
        for record in library.company_records(company):
            if record.review_status in ('source_verified','user_verified'):
                assert all((record.source_file,p) in selected for p in packs._int_pages(record.source_page))
        repeated = packs.refresh(company)
        assert repeated['reused'] and repeated['pdf_text_extractions'] == repeated['page_renders'] == 0
        results.append({'company':company, 'verified_pages':len(index), 'every_printed_page_stream_matches_original':True,
                        'all_reviewed_record_pages_included':True, 'artifact_hashes_valid':True,
                        'repeat_refresh_seconds':repeated['elapsed_seconds'], 'repeat_extractions_and_renders':0})
        print(json.dumps(results[-1]), flush=True)
    out = storage.PROJECT_DIR / 'reports/company-evidence-verification.json'
    out.write_text(json.dumps({'checked_at':storage.now(), 'companies':results}, indent=2))
