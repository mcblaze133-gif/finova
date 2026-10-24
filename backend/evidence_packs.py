"""Incremental, local evidence shortlists. Original documents remain authoritative.

Selection is deliberately not financial verification. Facts stay in library_records;
the pack is a dated evidence view with original page numbers and content hashes.
"""
import hashlib
import html
import json
import re
import shutil
import subprocess
import threading
import time
from importlib.metadata import version as package_version
from pathlib import Path
from backend import storage, library

VERSION = 'evidence-pack-2-history'
# The printed-page copying format has not changed. Reuse existing page previews.
COPY_VERSION = 'evidence-pack-1'
LOCK = threading.Lock()
TOPICS = {
    'statements': r'consolidated\s+(?:balance sheet|statement of (?:profit|cash)|cash flow)|cash flow statement|statement of cash flows|revenue from operations|total comprehensive income',
    'tax and exceptions': r'(?:income tax expense|exceptional items|restatement|prior.period tax)',
    'capital and obligations': r'(?:borrowings|lease liabilities|contingent liabilities|earnings per share|dividends|capital commitments)',
    'working capital and assets': r'(?:trade receivables|trade payables|inventories|capital expenditure|investments|segment information)',
    'operating drivers': r'(?:volume growth|tonnage|price.mix|rural demand|commodity|commodities|premiumi[sz]|distribution|capacity|market share)',
    'quarterly financials and costs': r'(?:key financial|net sales|revenue trends|input costs|cost efficiency|ebitda|profit after tax|gross profit|adjacency businesses|key states|general trade)',
    'guidance and delivery': r'(?:guidance|outlook|management expects|we expect|our target|capacity expansion|margin recovery|volume recovery|pricing action)',
    'comparability and business changes': r'(?:restat(?:ed|ement)|discontinued operations|demerger|acquisition|change in accounting|exceptional items|one.off|non.recurring)',
}


def digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pack_root(company):
    if not re.fullmatch(r'[a-z0-9-]{2,60}', company):
        raise ValueError('Use a lower-case company slug.')
    return storage.PROJECT_DIR / 'company-packs' / company


def read_manifest(company):
    path = pack_root(company) / 'manifest.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def source_fingerprints(company):
    root = library.root_folder()
    folder = library.company_folder(company).name.casefold()
    result = {}
    for entry in library.inventory()['files']:
        relative = entry['relative_path']
        if relative.split('/')[0].casefold() == folder and entry['type'] == 'pdf':
            result[relative] = digest_file(root / relative)
    return result


def document_kind(path, pages):
    name = path.lower()
    cover = ' '.join(pages.get(n, '')[:5000] for n in range(1, 4)).lower()
    if len(pages) > 80 and (re.search(r'annual|report|\bar[ _-]', name)
                            or re.search(r'annual\s+report|report\s+and\s+accounts', cover)):
        return 'annual'
    if re.search(r'transcript|trancript|earnings|call', name):
        return 'call'
    if re.search(r'deck|presentation|analyst|investormeet|prest', name):
        return 'presentation'
    return 'financial update'


def stale_records(records, fingerprints):
    return [r for r in records if r.source_file not in fingerprints or
            (r.source_sha256 and r.source_sha256 != fingerprints[r.source_file])]


def select_pages(pages, mandatory=(), annual=False, detailed=True):
    """Keep complete original pages plus neighboring context; never crop tables."""
    selected = {}
    for number in mandatory:
        if number in pages:
            selected.setdefault(number, []).append('reviewed financial record')
    headers = [p for p, t in pages.items() if re.search(
        r'consolidated\s+(?:balance sheet|statement of profit)', t, re.I)
        and re.search(r'non.current assets|revenue from operations', t, re.I)] if annual else []
    if annual and detailed:
        for topic in ('operating drivers','guidance and delivery','comparability and business changes'):
            ranked=sorted(((len(re.findall(TOPICS[topic],text,re.I)),number) for number,text in pages.items()
                           if not headers or number<min(headers)),reverse=True)
            for hits,number in ranked[:3]:
                if hits:selected.setdefault(number,[]).append(topic+' (historical operating commentary)')
    for number, text in pages.items():
        # Annual reports: restrict to the consolidated financial section when a
        # clear header exists, avoiding standalone duplication and audit boilerplate.
        if annual and (not headers or number < min(headers)):
            # Financial statement pages keep their explicit reporting scope.
            # Operating commentary before the consolidated accounts is also
            # needed to compare historical guidance with later delivery.
            continue
        topics = [name for name, pattern in TOPICS.items() if (detailed or name in ('statements', 'tax and exceptions'))
                  and re.search(pattern, text, re.I)]
        if topics:
            selected.setdefault(number, []).extend(topics)
    # Preserve one neighboring page each side for notes/table continuations.
    for number in list(selected):
        for neighbor in (number - 1, number + 1):
            if neighbor in pages:
                selected.setdefault(neighbor, []).append('adjacent context')
    return {p: sorted(set(reasons)) for p, reasons in sorted(selected.items())}


def period_hint(path, text):
    """Unverified reporting-period sort key, never a publication date."""
    cover = text.get(1, '')
    q = re.search(r'Q\s*([1-4])\s*[^\d]{0,8}((?:20)?\d{2}(?:\s*[-_/]\s*\d{2,4})?)', cover, re.I)
    if not q:
        q = re.search(r'Q\s*([1-4])\s*[^\d]{0,8}((?:20)?\d{2}(?:\s*[-_/]\s*\d{2,4})?)', path, re.I)
    if q:
        years = re.findall(r'(?:20)?(\d{2})(?!\d)', q[2])
        return (max(int(y) for y in years), int(q[1]))
    clean = re.sub(r'_[a-f0-9]{10}(?=\.pdf)', '', path.lower())
    years = re.findall(r'(?<!\d)(?:20)?(2\d)(?!\d)', clean)
    # Date-stamped opaque names, e.g. ...Meet04082026signed.pdf.
    years += re.findall(r'20(2\d)', clean)
    years += re.findall(r'\b20(2\d)\b', cover[:1500])
    return (max((int(y) for y in years), default=0), 0)


def _int_pages(value):
    return [int(n) for n in re.findall(r'\d+', str(value or ''))]


def _valid_artifacts(folder, hashes):
    return bool(hashes) and all((folder / p).is_file() and digest_file(folder / p) == h
                               for p, h in hashes.items())


def text_signature(company, fingerprints):
    active = set(fingerprints.values())
    digest = hashlib.sha256()
    for page in storage.rows('SELECT d.sha256,p.pdf_page,p.text FROM passages p JOIN documents d ON d.id=p.document_id WHERE d.company=? ORDER BY d.sha256,p.pdf_page', (company,)):
        if page['sha256'] in active:
            digest.update(json.dumps(page, sort_keys=True).encode('utf-8'))
    return digest.hexdigest()


def refresh(company):
    with LOCK:
        result=_refresh(company)
        from backend import statement_intake
        result['statement_intake']=statement_intake.scan(company,result['source_fingerprints'])
        return result


def _refresh(company):
    from pypdf import PdfReader, PdfWriter
    from pypdf.errors import PdfReadError
    started = time.perf_counter()
    # A reviewed image-only table must not disappear merely because the PDF has
    # no text layer. A separate, explicitly labelled record index enables its
    # physical source page to enter the pack without fabricating OCR text.
    from backend import reviewed_pages
    reviewed_pages.ensure(company)
    root = pack_root(company)
    root.mkdir(parents=True, exist_ok=True)
    fingerprints = source_fingerprints(company)
    records = library.company_records(company)
    stale = stale_records(records, fingerprints)
    signature_inputs = {'version': VERSION, 'selector_sha256': digest_file(__file__),
        'local_parser_sha256': digest_file(library.__file__),
        'font_decoder': package_version('fonttools'), 'pypdf': package_version('pypdf'), 'sources': fingerprints,
        'records': [r.model_dump(mode='json') for r in records]}
    def current_signature():
        return hashlib.sha256(json.dumps(dict(signature_inputs, text_sha256=text_signature(company, fingerprints)), sort_keys=True).encode()).hexdigest()
    signature = current_signature()
    old = read_manifest(company)
    if old and old['signature'] == signature and _valid_artifacts(root, old['artifact_hashes']):
        return dict(old, reused=True, elapsed_seconds=round(time.perf_counter()-started, 3),
                    pdf_text_extractions=0, page_renders=0)
    counters = {'pdf_text_extractions': 0, 'page_renders': 0}
    warnings = ['Automatic shortlist: inclusion does not verify figures; omitted pages may contain material context.',
                'Publication dates are not inferred from upload times. Latest updates still need dated external research.']
    if stale:
        warnings.append(f'{len(stale)} financial records have missing or changed source files; re-review required.')
    docs = []
    for relative, digest in sorted(fingerprints.items()):
        found = storage.rows('SELECT id,local_path FROM documents WHERE company=? AND sha256=?', (company, digest))
        if not found:
            try:
                library.import_pdf(company, relative)
            except Exception as exc:
                # A malformed/scanned/oversized document cannot silently disappear.
                reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                warnings.append(f'Unreadable document: {relative}: {reason[:220]}. Manual review required.')
                continue
            counters['pdf_text_extractions'] += 1
            found = storage.rows('SELECT id,local_path FROM documents WHERE company=? AND sha256=?', (company, digest))
        # Keep the active path mapping current even when content already exists.
        with storage.database() as db:
            db.execute('DELETE FROM library_documents WHERE company=? AND relative_path=?', (company, relative))
            db.execute('INSERT INTO library_documents(company,relative_path,document_id) VALUES(?,?,?)', (company, relative, found[0]['id']))
        text = {r['pdf_page']: r['text'] for r in storage.rows(
            'SELECT pdf_page,text FROM passages WHERE document_id=? ORDER BY pdf_page', (found[0]['id'],))}
        mandatory = [p for r in records if r.source_file == relative and (not r.source_sha256 or r.source_sha256 == digest)
                     and r.review_status in ('source_verified', 'user_verified') for p in _int_pages(r.source_page)]
        kind = document_kind(relative, text)
        annual = kind == 'annual'
        docs.append({'source_file': relative, 'sha256': digest, 'document_id': found[0]['id'],
                     'original': found[0]['local_path'], 'text_pages': len(text), 'annual': annual,
                     'mandatory': mandatory, 'period_hint': period_hint(relative, text), 'text': text, 'kind': kind})
    with storage.database() as db:
        for row in db.execute('SELECT id,relative_path FROM library_documents WHERE company=?', (company,)).fetchall():
            if row['relative_path'] not in fingerprints:
                db.execute('DELETE FROM library_documents WHERE id=?', (row['id'],))
    annuals = [d for d in docs if d['annual']]
    for doc in docs:
        # All available periods participate. There is no newest-two transcript
        # or presentation cutoff, and older annual notes receive equal depth.
        doc['selected'] = select_pages(doc['text'], doc['mandatory'], doc['annual'],
                                      detailed=True)
        has_consolidated_header=any(re.search(r'consolidated\s+(?:balance sheet|statement of profit)',text,re.I)
                                    and re.search(r'non.current assets|revenue from operations',text,re.I) for text in doc['text'].values())
        if doc['annual'] and (not doc['selected'] or not has_consolidated_header):
            # Some companies report only standalone financials. Keep labelled
            # statement candidates rather than pretending consolidated data exists.
            doc['selected'] = select_pages(doc['text'], doc['mandatory'], annual=False,
                                            detailed=True)
            warnings.append(f'Consolidated section not identified in {doc["source_file"]}; scope requires manual review.')
        if not doc['text']:
            warnings.append(f'No searchable text in {doc["source_file"]}; OCR/manual review required.')
        elif not doc['selected']:
            # Record an explicit review lead rather than silently dropping a
            # readable source whose terminology was not recognized.
            doc['selected']={n:['unclassified source: manual topic review required'] for n in sorted(doc['text'])[:2]}
            warnings.append(f'No financial topic matched in {doc["source_file"]}; opening pages retained for review.')
    if not annuals:
        warnings.append('No annual report identified. Quarterly releases do not replace the complete annual financial notes.')
    seen_content = {}
    for doc in docs:
        if doc['sha256'] in seen_content and not doc['mandatory']:
            doc['selected'] = {}
            doc['duplicate_of'] = seen_content[doc['sha256']]
        else:
            seen_content[doc['sha256']] = doc['source_file']
    # Immutable version folders make publication atomic and preserve past audit views.
    signature = current_signature()  # Include pages first imported during this refresh.
    version = root / 'versions' / signature
    version.mkdir(parents=True, exist_ok=True)
    combined, index = PdfWriter(), []
    prior_previews={}
    if old and old.get('pages'):
        previous_pages=root/old['pages']
        if previous_pages.is_file() and digest_file(previous_pages)==old.get('artifact_hashes',{}).get(old['pages']):
            for page in json.loads(previous_pages.read_text(encoding='utf-8')):
                name=page.get('screenshot','')
                image=(root/name).resolve()
                if image.is_relative_to(root.resolve()) and image.is_file() and digest_file(image)==old.get('artifact_hashes',{}).get(name):
                    prior_previews[(page['source_sha256'],page['original_page'])]=image
    renderer = shutil.which('pdftoppm')
    if not renderer:
        raise ValueError('PDF preview renderer pdftoppm is unavailable; original sources are unchanged.')
    for doc in docs:
        selected = doc['selected']
        if not selected:
            continue
        key = hashlib.sha256(json.dumps([COPY_VERSION, doc['sha256'], list(selected)]).encode()).hexdigest()
        folder = root / 'documents' / key
        folder.mkdir(parents=True, exist_ok=True)
        cache = folder / 'cache.json'
        cached = json.loads(cache.read_text()) if cache.exists() else {}
        if not _valid_artifacts(folder, cached.get('hashes', {})):
            reader = PdfReader(storage.PROJECT_DIR / doc['original'])
            writer = PdfWriter()
            copy_warnings = []
            try:
                for number in selected:
                    # Article threads are navigation metadata, not printed text.
                    writer.add_page(reader.pages[number-1], excluded_keys=['/B'])
            except (RecursionError, PdfReadError) as exc:
                if not isinstance(exc, RecursionError) and 'RecursionError' not in str(exc):
                    raise
                # Some PDF hyperlinks recursively reference the entire page tree.
                # Preserve printed contents/resources; originals retain annotations.
                reader, writer = PdfReader(storage.PROJECT_DIR / doc['original']), PdfWriter()
                for number in selected:
                    writer.add_page(reader.pages[number-1], excluded_keys=['/B', '/Annots'])
                copy_warnings.append(f'Interactive annotations omitted from derived pages of {doc["source_file"]} because recursive PDF links prevented copying. Printed page contents retained; check original for annotations.')
            writer.write(folder / 'selected.pdf')
            missing=[]
            for number in selected:
                prior=prior_previews.get((doc['sha256'],number))
                destination=folder/f'page-{number:04}.png'
                if prior:
                    if prior!=destination.resolve():shutil.copyfile(prior,destination)
                else:missing.append(number)
            if missing:
                # Render newly selected original pages only. Existing images
                # are reused only after checking source SHA, original page and
                # the previously published image hash.
                render_writer=PdfWriter()
                positions={n:i for i,n in enumerate(selected)}
                for number in missing:
                    render_writer.add_page(writer.pages[positions[number]],excluded_keys=['/B','/Annots'])
                render_pdf=folder/'render-pending.pdf'
                render_writer.write(render_pdf)
                result = subprocess.run([renderer, '-png', '-scale-to', '1800', str(render_pdf),
                                         str(folder / 'preview')], capture_output=True, timeout=300)
                if result.returncode:
                    raise ValueError('Evidence page rendering failed; pack has not been published.')
                previews = sorted(folder.glob('preview-*.png'))
                if len(previews) != len(missing):
                    raise ValueError('Preview count does not match selected pages.')
                for number, preview in zip(missing, previews):
                    preview.replace(folder / f'page-{number:04}.png')
                render_pdf.unlink()
                counters['page_renders'] += len(missing)
            hashes = {p.name: digest_file(p) for p in folder.iterdir() if p.suffix in ('.pdf', '.png')}
            cache.write_text(json.dumps({'hashes': hashes, 'warnings': copy_warnings}), encoding='utf-8')
            cached = {'warnings': copy_warnings}
        warnings.extend(cached.get('warnings', []))
        combined.append(str(folder / 'selected.pdf'), import_outline=False)
        for number, reasons in selected.items():
            index.append({'pack_page': len(index)+1, 'source_file': doc['source_file'],
                          'source_sha256': doc['sha256'], 'original_page': number,
                          'reasons': reasons, 'text': doc['text'][number],
                          'document_kind':doc['kind'],
                          'period_sort_hint_unverified':doc['period_hint'],
                          'screenshot': (folder / f'page-{number:04}.png').relative_to(root).as_posix()})
    if not index:
        raise ValueError('No searchable valuation evidence found. Originals require manual review or OCR.')
    combined.write(version / 'valuation-evidence.pdf')
    (version / 'pages.json').write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
    facts = [dict(r.model_dump(mode='json'), source_current=r not in stale) for r in records]
    (version / 'financial-records.json').write_text(json.dumps(facts, indent=2), encoding='utf-8')
    cards = ''.join(f'<article><h2>Pack page {p["pack_page"]} / original page {p["original_page"]}</h2>'
                    f'<p>{html.escape(p["source_file"])}<br>{html.escape(", ".join(p["reasons"]))}</p>'
                    f'<a href="../../{p["screenshot"]}"><img loading="lazy" width="650" src="../../{p["screenshot"]}"></a></article>' for p in index)
    (version / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Company evidence pack</title>'
        '<style>body{font:16px system-ui;background:#eef2f5;color:#17283b;max-width:1000px;margin:30px auto}article{background:white;padding:24px;margin:20px 0}img{max-width:100%}</style>'
        f'<h1>{html.escape(company.title())} valuation evidence</h1><p>Automatic shortlist. Full originals retained. '
        'Original PDF page numbers are one-based, including covers. Selection is not verification.</p>'
        '<p><a href="valuation-evidence.pdf">Open combined PDF</a> | <a href="financial-records.json">Financial record provenance</a></p>'+cards, encoding='utf-8')
    relative_version = version.relative_to(root).as_posix()
    (root / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Company evidence</title>'
        '<style>body{font:18px system-ui;max-width:800px;margin:60px auto;color:#17283b}a{color:#116a61}li{margin:20px 0}</style>'
        f'<h1>{html.escape(company.title())} evidence pack</h1><p>{len(index)} selected original pages from {len(docs)} PDFs. '
        'Full original documents are retained. Automatic selection requires review.</p><ul>'
        f'<li><a href="{relative_version}/valuation-evidence.pdf">Open selected evidence PDF</a></li>'
        f'<li><a href="{relative_version}/index.html">Browse screenshot previews and original page references</a></li>'
        f'<li><a href="{relative_version}/financial-records.json">View financial records and source provenance</a></li></ul>'
        f'<p>Prepared {html.escape(storage.now())}. Refresh from Finova to check for changed files.</p>', encoding='utf-8')
    artifact_hashes = {p.relative_to(root).as_posix(): digest_file(p) for p in version.iterdir() if p.is_file()}
    artifact_hashes['index.html'] = digest_file(root / 'index.html')
    for page in index:
        artifact_hashes[page['screenshot']] = digest_file(root / page['screenshot'])
    manifest = {'version': VERSION, 'company': company, 'signature': signature, 'created_at': storage.now(),
                'history_policy':'All available annual reports, financial releases, presentations and transcripts; period hints are unverified grouping labels, not dates or financial facts.',
                'input_files': len(fingerprints), 'unreadable_files': len(fingerprints)-len(docs),
                'source_files': len(docs), 'source_text_pages': sum(d['text_pages'] for d in docs),
                'selected_pages': len(index), 'reviewed_records': len(records), 'stale_records': len(stale),
                'source_fingerprints': fingerprints, 'warnings': warnings, 'artifact_hashes': artifact_hashes,
                'source_index': [{'source_file': d['source_file'], 'sha256': d['sha256'],
                                  'kind': d['kind'], 'duplicate_of': d.get('duplicate_of'),
                                  'period_sort_hint_unverified': d['period_hint'],
                                  'selected_original_pages': list(d['selected'])} for d in docs],
                'pdf': (version / 'valuation-evidence.pdf').relative_to(root).as_posix(),
                'index': (version / 'index.html').relative_to(root).as_posix(),
                'pages': (version / 'pages.json').relative_to(root).as_posix(),
                'reused': False, **counters, 'elapsed_seconds': round(time.perf_counter()-started, 3)}
    pending = root / 'manifest.pending.json'
    pending.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    pending.replace(root / 'manifest.json')
    return manifest


def search(company, query, limit=8, full=False):
    """Search shortlist first; fall back to full stored original page text."""
    terms = re.findall(r'\w+', query.lower())
    if not terms or len(query) > 300:
        raise ValueError('Supply a search phrase of 1 to 300 characters.')
    manifest = read_manifest(company)
    current = source_fingerprints(company)
    fresh = manifest and current == manifest['source_fingerprints']
    selected = json.loads((pack_root(company) / manifest['pages']).read_text(encoding='utf-8')) if fresh and not full else []
    def ranked(pages):
        matches = []
        for page in pages:
            text = page['text']
            score = sum(term in text.lower() for term in terms)
            if score == len(terms):
                start = max(0, text.lower().find(terms[0])-100)
                matches.append({k: v for k, v in page.items() if k != 'text'} | {'snippet': text[start:start+700]})
        return matches[:max(1, min(limit, 20))]
    hits = ranked(selected)
    if hits:
        return {'scope': 'evidence shortlist', 'results': hits, 'requires_source_review': True}
    full = storage.rows('SELECT DISTINCT p.text,p.pdf_page AS original_page,d.sha256 AS source_sha256,l.relative_path AS source_file '
        'FROM passages p JOIN documents d ON p.document_id=d.id JOIN library_documents l ON l.document_id=d.id WHERE l.company=?', (company,))
    full = [r for r in full if current.get(r['source_file']) == r['source_sha256']]
    return {'scope': 'full original fallback', 'results': ranked(full), 'requires_source_review': True,
            'refresh_required': not bool(fresh)}
