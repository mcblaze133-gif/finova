"""Prepare cached local packs and optionally publish copies beside user originals.

No model calls, no market lookup, and no automatic financial verification.
"""
import argparse
import csv
import html
import json
import shutil
from pathlib import Path
from pypdf import PdfReader
from backend import storage, library, evidence_packs as packs


def write_text(path, value):
    pending = path.with_name(path.name + '.pending')
    pending.write_text(value, encoding='utf-8')
    pending.replace(path)


def prepare(company):
    folder = library.company_folder(company)
    originals = [p for p in library.inventory()['files']
                 if p['relative_path'].split('/')[0].casefold() == folder.name.casefold()]
    if not any(p['type'] == 'pdf' for p in originals):
        return {'company': company, 'folder': str(folder), 'status': 'empty',
                'message': 'No original PDFs found. Add annual reports, results, presentations or call transcripts.',
                'csv_files': sum(p['type'] == 'csv' for p in originals)}
    manifest = packs.refresh(company)
    root = packs.pack_root(company)
    pages = json.loads((root / manifest['pages']).read_text(encoding='utf-8'))
    pdf = PdfReader(root / manifest['pdf'])
    assert len(pdf.pages) == len(pages) == manifest['selected_pages']
    assert packs._valid_artifacts(root, manifest['artifact_hashes'])
    for n in sorted({0, len(pages)//2, len(pages)-1}):
        original = PdfReader(storage.DATA_DIR / 'raw' / (pages[n]['source_sha256'] + '.pdf')).pages[pages[n]['original_page']-1]
        actual = pdf.pages[n]
        assert actual.get_contents().get_data() == original.get_contents().get_data(), f'Page copy mismatch: {company} {n+1}'
        assert list(actual.mediabox) == list(original.mediabox), 'Copied page dimensions changed'
    return {'company': company, 'folder': str(folder), 'status': 'prepared',
            'pdfs': manifest.get('input_files', manifest['source_files']),
            'readable_pdfs': manifest['source_files'], 'text_pages': manifest['source_text_pages'],
            'selected_pages': len(pages), 'warnings': manifest['warnings'],
            'signature': manifest['signature'], 'cached': manifest['reused'],
            'csv_files': sum(p['type'] == 'csv' for p in originals)}


def publish(result):
    folder = Path(result['folder']).resolve()
    assert folder == library.company_folder(result['company'])
    assert folder.parent == library.root_folder() and folder.is_dir()
    target = folder / 'SignalAI Evidence'
    if not target.resolve().is_relative_to(folder):
        raise ValueError('Generated folder points outside the company folder.')
    target.mkdir(exist_ok=True)
    if result['status'] != 'prepared':
        write_text(target / 'READ ME.txt', result['message'] + '\nNo valuation inputs were invented.\n')
        write_text(target / 'index.html', '<!doctype html><meta charset="utf-8"><h1>No company PDFs available</h1><p>'
                   + html.escape(result['message']) + '</p>')
        return
    root = packs.pack_root(result['company'])
    manifest = packs.read_manifest(result['company'])
    assert result['signature'] == manifest['signature']
    if packs.source_fingerprints(result['company']) != manifest['source_fingerprints']:
        raise ValueError('Original files changed during preparation. Refresh the pack before publication.')
    pages = json.loads((root / manifest['pages']).read_text(encoding='utf-8'))
    version = target / 'versions' / manifest['signature']
    if not version.resolve().is_relative_to(folder):
        raise ValueError('Generated version points outside the company folder.')
    version.mkdir(parents=True, exist_ok=True)
    source_pdf = root / manifest['pdf']
    final_pdf = version / 'Valuation evidence.pdf'
    shutil.copyfile(source_pdf, final_pdf.with_suffix('.pending'))
    final_pdf.with_suffix('.pending').replace(final_pdf)
    assert packs.digest_file(source_pdf) == packs.digest_file(final_pdf)
    with (version / 'Source index.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['Pack page', 'Original file', 'Original PDF page (including cover)', 'Selection topics', 'Source SHA256'])
        writer.writerows([p['pack_page'], p['source_file'], p['original_page'], '; '.join(p['reasons']), p['source_sha256']] for p in pages)
    text = ['AUTOMATIC EVIDENCE SHORTLIST - NOT VERIFIED FINANCIAL INPUTS',
            'Original PDF page numbers include covers. Source dates are not inferred from filenames.',
            'Search full original documents when this shortlist does not answer a question.\n']
    for page in pages:
        text += [f'\n=== Pack page {page["pack_page"]} | Original page {page["original_page"]} | {page["source_file"]} ===',
                 'Topics: ' + ', '.join(page['reasons']), page['text']]
    write_text(version / 'Searchable evidence.txt', '\n'.join(text))
    shutil.copyfile(root / manifest['pages'], version / 'Page evidence.json')
    shutil.copyfile((root / manifest['pages']).parent / 'financial-records.json', version / 'Financial records.json')
    write_text(version / 'Historical coverage.json',json.dumps({
        'prepared_at':manifest['created_at'],'policy':manifest.get('history_policy'),
        'warning':'Period sort hints are unverified retrieval groups, not event dates, validated financial years or proof of exhaustive review.',
        'sources':manifest['source_index'],'warnings':manifest['warnings']},indent=2))
    write_text(version / 'Coverage and warnings.txt',
        f'Company: {result["company"]}\nPrepared: {manifest["created_at"]}\n'
        f'Input PDFs: {result["pdfs"]}\nReadable PDFs: {result["readable_pdfs"]}\n'
        f'Selected pages: {len(pages)} of {result["text_pages"]} searchable pages\n'
        f'Existing reviewed records: {manifest["reviewed_records"]}\n'
        'All available annual reports, calls, presentations and financial releases participate, including older periods. '
        'Historical financial notes, operating drivers, guidance and business changes are selected at the same depth as recent material. '
        'Period hints diversify retrieval only; they do not establish dates, accounting periods or comparable financial values. '
        'The topic-based shortlist is not exhaustive.\n'
        'Text extraction may omit rotated text or misalign complex tables. Use the copied original PDF '
        'pages to verify tables and footnotes before accepting any numerical values.\n'
        'CSV files are inventoried but are not automatically promoted to verified financial records.\n\n'
        + '\n'.join(manifest['warnings']))
    rel = f'versions/{manifest["signature"]}/'
    links = ''.join(f'<li><a href="{rel}{name}">{label}</a></li>' for name, label in [
        ('Valuation%20evidence.pdf', 'Open selected original PDF pages'),
        ('Searchable%20evidence.txt', 'Search extracted evidence text'),
        ('Source%20index.csv', 'Original file and page index'),
        ('Coverage%20and%20warnings.txt', 'Coverage, missing data and warnings'),
        ('Historical%20coverage.json', 'Historical source coverage and unverified period groups'),
        ('Financial%20records.json', 'Existing reviewed financial records (may be empty)'),
        ('Page%20evidence.json', 'Structured page evidence for reuse')])
    write_text(target / 'index.html', '<!doctype html><meta charset="utf-8"><title>SignalAI evidence</title>'
        '<style>body{font:17px system-ui;max-width:850px;margin:50px auto;padding:15px;color:#142c43}li{margin:16px 0}</style>'
        f'<h1>{html.escape(folder.name)} - useful company evidence</h1>'
        f'<p>{len(pages)} selected pages from {result["readable_pdfs"]} readable PDFs. Original files are unchanged.</p>'
        '<p>This is a source shortlist, not a financial audit or completed valuation. Missing evidence must be reviewed.</p>'
        f'<ul>{links}</ul><p>Prepared {html.escape(manifest["created_at"])}</p>')
    published = {p.name: packs.digest_file(p) for p in version.iterdir() if p.is_file()}
    write_text(target / 'manifest.json', json.dumps(dict(result, published_files=published,
        version_folder=rel, prepared_at=manifest['created_at']), indent=2))
    result['published_pdf'] = str(final_pdf)
    result['published_index'] = str(target / 'index.html')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--company', action='append')
    args = parser.parse_args()
    storage.initialize()
    mapping = json.loads((storage.PROJECT_DIR / 'config/company_folders.json').read_text())
    summary_path = storage.PROJECT_DIR / 'reports/company-evidence-batch.json'
    # Publishing uses previously verified staging packs, so it never re-extracts.
    if args.publish:
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        for result in summary['companies']:
            if result['status'] in ('prepared', 'empty'):
                publish(result)
                print(json.dumps({'company': result['company'], 'status': 'published' if result['status']=='prepared' else 'empty-folder note saved'}), flush=True)
        summary['published_at'] = storage.now()
    else:
        summary = {'created_at': storage.now(), 'model_calls': 0, 'companies': []}
        for company in args.company or mapping:
            print(json.dumps({'company': company, 'status': 'preparing'}), flush=True)
            try:
                result = prepare(company)
            except Exception as exc:
                result = {'company': company, 'status': 'failed', 'error': str(exc)[:300]}
            summary['companies'].append(result)
            write_text(summary_path, json.dumps(summary, indent=2))
            print(json.dumps(result), flush=True)
    write_text(summary_path, json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
