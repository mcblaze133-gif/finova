"""Source-reviewed additions from HUL annual statements, never forecast estimates.

Run after PDF intake. Existing reviewed rows are retained. Conflicting source
values stop intake rather than silently replacing another review.
"""
import hashlib
import json
from decimal import Decimal

from backend import library, storage
from backend.excel_engine import normalized_value
from backend.valuation_spec import FinancialRecord

PREFIX = 'HUL annual statement supplement v1.'
SPECS = [
    (2022, 'HUL_Annual_Report_2021_22_nZY0do.pdf', 'total', {
        'ebitda': (12857, [113], '52446 - 40786 + 106 + 1091'),
        'ebit': (11766, [113], '52446 - 40786 + 106'),
        'debt': (1043, [112], 'Non-current leases741 + current leases302; no closing borrowings'),
        'operating_nwc': (-2736, [112], 'Inventories4096 + receivables2236 - payables60 - payables9008'),
        'shares': (2349591262, [128], 'Exact issued and fully paid closing share count'),
    }),
    (2023, 'hul-annual-report-2022-23-prfppu.pdf', 'total', {
        'ebitda': (14149, [140], '60580 - 47682 + 114 + 1137'),
        'ebit': (13012, [140], '60580 - 47682 + 114'),
        'debt': (1219, [139], 'Borrowings98 + non-current leases807 + current leases314'),
        'operating_nwc': (-2244, [139], 'Inventories4251 + receivables3079 - payables100 - payables9474'),
        'shares': (2349591262, [154], 'Exact issued and fully paid closing share count'),
    }),
    (2024, 'annual-report-2023-24.pdf', 'total', {
        'ebitda': (14663, [178], '61896 - 48783 + 334 + 1216'),
        'ebit': (13447, [178], '61896 - 48783 + 334'),
        'debt': (1484, [177], 'Borrowings13 + non-current leases1106 + current leases365'),
        'operating_nwc': (-3467, [177], 'Inventories4022 + receivables2997 - payables250 - payables10236'),
        'shares': (2349591262, [192], 'Exact issued and fully paid closing share count'),
    }),
    (2025, 'SignalAI_official_Annual_Report_FY2026.pdf', 'continuing', {
        'cfo': (11792, [370, 446], 'Total consolidated CFO11886 less discontinued CFO94 = continuing CFO11792'),
        'dividends': (12473, [371], 'Consolidated cash dividends paid, not dividends declared or proposed; includes group distributions'),
    }),
    (2026, 'SignalAI_official_Annual_Report_FY2026.pdf', 'continuing', {
        'cfo': (11071, [370, 446], 'Total consolidated CFO10999 less discontinued CFO(-72) = continuing CFO11071'),
        'dividends': (10124, [371], 'Consolidated cash dividends paid, not dividends declared or proposed; includes group distributions'),
    }),
]


def main():
    existing = library.company_records('hul')
    prepared = []
    audit = []
    for year, name, scope, metrics in SPECS:
        relative = 'HUL/reports/' + name
        docs = storage.rows('SELECT d.* FROM library_documents l JOIN documents d ON d.id=l.document_id WHERE l.company=? AND l.relative_path=?', ('hul', relative))
        if not docs:
            raise ValueError('Import the annual report first: ' + relative)
        doc = docs[0]
        path = library.root_folder() / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == doc['sha256']
        for metric, (value, pages, derivation) in metrics.items():
            quote = '\n'.join('PDF page ' + str(p) + ':\n' + '\n'.join(r['text'] for r in storage.rows('SELECT text FROM passages WHERE document_id=? AND pdf_page=?', (doc['id'], p))) for p in pages)
            if any(not storage.rows('SELECT id FROM passages WHERE document_id=? AND pdf_page=?', (doc['id'], p)) for p in pages):
                raise ValueError('Missing source page text: ' + relative)
            stock = metric in ('debt', 'operating_nwc', 'shares')
            explanation = derivation
            if metric in ('ebitda', 'ebit'):
                explanation += '. Revenue less total expenses, adding back finance cost and (for EBITDA) P&L D&A; excludes other income, exceptional items and equity-accounted results. Original annual expense basis, not later restated comparatives.'
            if scope == 'total':
                explanation += '. Historical pre-ice-cream-demerger perimeter, not restated to current continuing operations.'
            rec = FinancialRecord(company='hul', metric=metric, value=str(value),
                unit='shares' if metric == 'shares' else 'INR_crore',
                period_start=None if stock else f'{year-1}-04-01', period_end=f'{year}-03-31',
                accounting_scope='consolidated', operations_scope=scope,
                definition=explanation, source_type='historical', source_url=path.as_uri(),
                source_file=relative, source_page=','.join(map(str, pages)), source_date=f'{year}-03-31',
                review_status='source_verified', source_sha256=doc['sha256'], source_quote=quote[:8000],
                review_note=PREFIX + ' Source statement rows reviewed; signed discontinued CFO subtracted. '
                    'CFO can be reconciled without asserting that net investing cash flow equals capex. '
                    'Dividend amounts are group cash distributions, not a continuing-segment allocation.')
            others = [r for r in existing if r.metric == metric and r.period_end == rec.period_end
                      and r.accounting_scope == rec.accounting_scope and r.operations_scope == rec.operations_scope
                      and r.review_status in ('source_verified', 'user_verified')]
            if any(Decimal(str(normalized_value(r))) != Decimal(str(normalized_value(rec))) for r in others):
                raise ValueError(f'Conflicting existing reviewed {year} {metric}')
            payload = rec.model_dump_json()
            prepared.append((hashlib.sha256(payload.encode()).hexdigest(), 'hul', payload, doc['sha256'], storage.now()))
            audit.append(dict(year=year, metric=metric, value=value, unit=rec.unit, scope=scope,
                              source_file=relative, pages=pages, derivation=derivation))
    with storage.database() as db:
        db.executemany('INSERT OR IGNORE INTO library_records VALUES(?,?,?,?,?)', prepared)
    target = storage.PROJECT_DIR / 'reports/hul-annual-supplement.json'
    target.write_text(json.dumps({'created_at': storage.now(), 'records_checked': len(audit), 'records': audit}, indent=2), encoding='utf-8')
    print(f'Reviewed {len(audit)} HUL annual additions; original source hashes and conflicts checked.')


if __name__ == '__main__':
    main()
