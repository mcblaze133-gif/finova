"""Read-only intake from the user's PDF/CSV folder; no directory modifications."""
import csv
import hashlib
import json
from pathlib import Path
from pydantic import ValidationError
from backend import storage
from backend.valuation_spec import FinancialRecord


def root_folder():
    config = json.loads((storage.PROJECT_DIR / 'config/library.json').read_text(encoding='utf-8'))
    return Path(config['source_folder']).resolve()


def inventory():
    root = root_folder()
    files = []
    if root.is_dir():
        for path in root.rglob('*'):
            # Derived packs must never be re-ingested as original evidence.
            if any(part.casefold() == 'signalai evidence' for part in path.relative_to(root).parts):
                continue
            if path.suffix.lower() in ('.pdf', '.csv') and path.is_file():
                resolved = path.resolve()
                if resolved.is_relative_to(root):
                    files.append({'relative_path': path.relative_to(root).as_posix(),
                                  'type': path.suffix.lower()[1:], 'bytes': path.stat().st_size})
    return {'source_folder': str(root), 'exists': root.is_dir(), 'files': files,
            'pdfs': sum(f['type'] == 'pdf' for f in files), 'csvs': sum(f['type'] == 'csv' for f in files),
            'status': 'empty' if not files else 'available'}


def company_folder(company):
    config = storage.PROJECT_DIR / 'config/company_folders.json'
    mapping = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
    name = mapping.get(company, company)
    root = root_folder()
    candidate = (root / name).resolve()
    if candidate.parent != root or not isinstance(name, str):
        raise ValueError('Company folders must be direct children of the source folder.')
    return candidate


def import_csv(relative_path):
    root = root_folder()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != '.csv' or not path.is_file():
        raise ValueError('Choose an existing CSV inside the configured source folder.')
    if path.stat().st_size > 10_000_000:
        raise ValueError('CSV exceeds 10 MB intake limit.')
    raw = path.read_bytes()
    file_hash = hashlib.sha256(raw).hexdigest()
    records, errors = [], []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            if line > 10002:
                raise ValueError('CSV exceeds 10,000 records.')
            try:
                clean = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                if not clean.get('period_start'):
                    clean['period_start'] = None
                for optional in ('source_sha256','source_quote','review_note'):
                    if optional in clean and not clean[optional]:
                        clean[optional] = None
                record = FinancialRecord.model_validate(clean)
                source_path = (root / record.source_file).resolve()
                if not source_path.is_relative_to(root) or not source_path.is_file():
                    raise ValueError('Referenced source file is missing or outside the source folder.')
                if record.review_status == 'source_verified' and hashlib.sha256(source_path.read_bytes()).hexdigest() != record.source_sha256:
                    raise ValueError('Reviewed source hash does not match the actual file.')
                payload = record.model_dump(mode='json')
                record_id = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                records.append((record_id, record.company, json.dumps(payload), file_hash, storage.now()))
            except (ValidationError, ValueError, TypeError):
                errors.append({'line': line, 'reason': 'Invalid fields, amount, period or source-file reference.'})
    # Atomic intake: a partly malformed financial CSV must not silently contribute
    # a biased subset of its records to a valuation.
    if errors:
        return {'imported': 0, 'errors': errors, 'status': 'rejected'}
    with storage.database() as db:
        before = db.total_changes
        db.executemany('INSERT OR IGNORE INTO library_records VALUES(?,?,?,?,?)', records)
        inserted = db.total_changes - before
    return {'status': 'imported', 'records_checked': len(records), 'imported': inserted,
            'review': 'Only rows explicitly marked user_verified are eligible for the workbook. Import is not an audit of the original PDF.'}


def company_records(company):
    return [FinancialRecord.model_validate_json(row['record_json']) for row in storage.rows(
        'SELECT record_json FROM library_records WHERE company=?', (company,))]


def import_pdf(company, relative_path, original_url=None, source_date=None):
    from backend.documents import save_document
    import re
    if not re.fullmatch(r'[a-z0-9-]{2,60}', company) or (original_url is not None and not original_url.startswith('https://')):
        raise ValueError('Use a company slug and, when known, an original public HTTPS source URL.')
    root = root_folder()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != '.pdf':
        raise ValueError('Choose a PDF inside the configured source folder.')
    # User-prepared annual reports can contain large high-resolution images.
    # Keep the remote download ceiling separate; page/content limits still apply
    # during extraction of this explicitly selected local file.
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Local PDF exceeds the 128 MB intake limit.')
    data = path.read_bytes()
    if not data.startswith(b'%PDF-'):
        raise ValueError('The selected file is not a PDF.')
    digest = hashlib.sha256(data).hexdigest()
    existing = storage.rows('SELECT id FROM documents WHERE company=? AND sha256=?', (company, digest))
    if existing:
        document_id = existing[0]['id']
    else:
        from pypdf.errors import LimitReachedError
        try:
            document_id = save_document(company, original_url or path.as_uri(), path.stem, data, 'application/pdf', source_date)
        except (LimitReachedError, ValueError) as exc:
            if not isinstance(exc, LimitReachedError) and not any(message in str(exc) for message in
                    ('No usable PDF text', 'PDF exceeds extracted text limit.')):
                raise
            pages = extract_local_pdf_fallback(path)
            document_id = save_document(company, original_url or path.as_uri(), path.stem, data,
                                        'application/pdf', source_date, extracted_pages=pages)
    with storage.database() as db:
        db.execute('DELETE FROM library_documents WHERE company=? AND relative_path=?',
                   (company, path.relative_to(root).as_posix()))
        db.execute('INSERT OR IGNORE INTO library_documents(company,relative_path,document_id,source_date) VALUES(?,?,?,?)',
                   (company, path.relative_to(root).as_posix(), document_id, source_date))
    return {'document_id': document_id, 'status': 'text imported',
            'financial_review': 'PDF text is evidence, not automatically verified financial inputs.'}


def extract_local_pdf_fallback(path):
    """Alternative local parser for complex vector PDFs; same page/text bounds."""
    import shutil
    import subprocess
    import tempfile
    from pypdf import PdfReader
    from backend.documents import MAX_PAGES, MAX_TEXT
    reader = PdfReader(path)
    if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
        raise ValueError('Local PDF is encrypted or exceeds the page limit.')
    renderer = shutil.which('pdftotext')
    if not renderer:
        bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftotext.exe'
        renderer = str(bundled) if bundled.is_file() else None
    def plain_text():
        # Some annual reports have very wide/spread layouts. Layout extraction
        # can exceed its padded-text bound although the ordinary text layer is
        # small and readable. Preserve physical page numbers and the same byte,
        # page-content and extracted-text limits. This is text extraction, not OCR.
        pages, length = [], 0
        for page in reader.pages:
            content = page.get_contents()
            if content and len(content.get_data()) > 10_000_000:
                raise ValueError('PDF page exceeds extraction limit.')
            text = page.extract_text() or ''
            length += len(text)
            if length > MAX_TEXT:
                raise ValueError('Alternative PDF extraction exceeded text limits.')
            pages.append(text)
        if sum(len(p.strip()) for p in pages) < 80:
            raise ValueError('No usable PDF text after both parsers; OCR/manual review required.')
        return pages
    if not renderer:
        return plain_text()
    temp_root = storage.PROJECT_DIR / 'tmp/pdf-text'
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=temp_root) as scratch:
            text_path = Path(scratch) / 'text.txt'
            result = subprocess.run([renderer, '-layout', '-enc', 'UTF-8', str(path), str(text_path)],
                                    capture_output=True, timeout=120)
            if result.returncode or not text_path.is_file() or text_path.stat().st_size > MAX_TEXT * 4:
                return plain_text()
            text = text_path.read_text(encoding='utf-8')
    except (OSError, subprocess.TimeoutExpired):
        return plain_text()
    pages = text.split('\f')
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != len(reader.pages) or sum(len(p) for p in pages) > MAX_TEXT:
        return plain_text()
    if sum(len(p.strip()) for p in pages) < 80:
        return plain_text()
    return pages


def observed_drivers(company):
    patterns = {'volume': r'\bvolume\b', 'pricing': r'\bpricing\b|\bprice increases?\b',
                'premiumisation': r'premiumisation|premiumization', 'rural_demand': r'rural demand|rural consumption',
                'distribution': r'distribution|outlet additions?', 'ecommerce': r'e-commerce|ecommerce|quick commerce',
                'commodities': r'raw materials?|commodity|palm oil|packaging', 'advertising': r'advertising|brand investment',
                'working_capital': r'working capital|inventories|receivables', 'capacity': r'capacity|capital expenditure',
                'acquisitions': r'acquisition|demerger|disposal', 'segments': r'segment results|segment revenue'}
    import re
    result = []
    pages = storage.rows('SELECT p.id,p.text,d.original_url,p.pdf_page FROM passages p JOIN documents d ON d.id=p.document_id JOIN library_documents l ON l.document_id=d.id WHERE l.company=?', (company,))
    for driver, pattern in patterns.items():
        for page in pages:
            text = ' '.join(page['text'].split())
            match = re.search(pattern, text, re.I)
            if match:
                result.append({'driver': driver, 'source': page['original_url'], 'passage_id': page['id'],
                               'page': page['pdf_page'], 'quote': text[max(0,match.start()-80):match.end()+140],
                               'confidence': 'unassessed', 'source_type': 'classification required',
                               'meaning': 'Text occurrence; relevance and economic impact need source review.'})
                break
    return result
