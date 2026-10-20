"""Reviewed as-reported statements, kept separate from forecast assumptions."""
from backend import storage, library
from backend.evidence_packs import digest_file

METRICS = ['revenue','ebitda','da','ebit','net_income','cfo','capex','dividends',
           'assets','liabilities','book_equity','nci','debt','cash','operating_nwc','shares','interest']
LABELS = {'revenue':'Revenue','ebitda':'Operating EBITDA','da':'Depreciation & amortisation',
          'ebit':'Operating EBIT','net_income':'Profit attributable to shareholders',
          'cfo':'Operating cash flow','capex':'Capital expenditure','dividends':'Dividends paid',
          'assets':'Total assets','liabilities':'Total liabilities','book_equity':'Parent book equity',
          'nci':'Non-controlling interests','debt':'Debt including leases','cash':'Cash & equivalents',
          'operating_nwc':'Core trade working capital','shares':'Closing shares','interest':'Finance cost'}

def reviewed_records(company):
    hashes={}
    eligible=[]
    for r in library.company_records(company):
        if r.review_status not in ('user_verified','source_verified') or r.source_type!='historical' or r.segment!='group':continue
        if max(r.source_date,r.period_end)>storage.today_ist():continue
        if r.source_sha256:
            path=(library.root_folder()/r.source_file).resolve()
            if path not in hashes:
                hashes[path]=digest_file(path) if path.is_relative_to(library.root_folder()) and path.is_file() else None
            if hashes[path]!=r.source_sha256:continue
        eligible.append(r)
    return eligible

def build(company, records=None):
    from backend.excel_engine import normalized_value
    records=reviewed_records(company) if records is None else records
    periods=[];issues=[]
    # Revenue establishes a flow period. Stocks join only on exact closing date
    # and reporting scope; a 15-month period is never relabelled as a year.
    keys=sorted({(r.period_end,r.period_start,r.accounting_scope,r.operations_scope) for r in records
                 if r.metric=='revenue' and r.period_start and (r.period_end-r.period_start).days>=300})
    docs={r['sha256']:r['id'] for r in storage.rows('SELECT id,sha256 FROM documents WHERE company=?',(company,))}
    for end,start,accounting,operations in keys:
        days=(end-start).days+1
        matches=[r for r in records if r.period_end==end and r.accounting_scope==accounting and r.operations_scope==operations
                 and (r.period_start is None or r.period_start==start)]
        values={};sources={}
        for metric in METRICS:
            found=[r for r in matches if r.metric==metric]
            numbers={normalized_value(r) for r in found}
            if len(numbers)>1:
                issues.append(f'{end}: conflicting {LABELS[metric]} on {accounting}/{operations} basis; excluded.')
                continue
            if len(numbers)!=1:continue
            values[metric]=next(iter(numbers))
            sources[metric]=[]
            for r in found:
                doc_id=docs.get(r.source_sha256)
                first_page=(r.source_page or '1').split(',')[0]
                sources[metric].append(dict(file=r.source_file,pages=r.source_page,
                    url=f'/documents/{doc_id}/original#page={first_page}' if doc_id else None,
                    definition=r.definition,sha256=r.source_sha256))
        periods.append(dict(start=start.isoformat(),end=end.isoformat(),duration_days=days,
            label=f'{start:%b %Y}–{end:%b %Y}',scope=f'{accounting} · {operations} operations',
            accounting_scope=accounting,operations_scope=operations,values=values,sources=sources,
            qualification='15-month reporting period; not annualised.' if days>400 else 'As reported; acquisitions, restatements and demergers can change comparability.'))
    return dict(periods=periods,metrics=[dict(id=m,label=LABELS[m]) for m in METRICS],issues=issues,
        qualification='Amounts in ₹ crore; shares shown as actual shares. Missing means unverified or unavailable, never zero. Different scopes and reporting lengths must not be treated as like-for-like growth.',
        investor_use='Compare recurring profit with operating cash flow and capital spending to test earnings quality and reinvestment needs. Check reporting scope before judging a trend; older statements do not automatically justify a forecast.')
