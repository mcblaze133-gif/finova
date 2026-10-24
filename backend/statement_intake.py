"""Source-linked annual-statement candidates. Promotion requires recorded review."""
import calendar
import hashlib
import json
import re
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
from backend import storage,library
from backend.valuation_spec import FinancialRecord

VERSION='annual-two-column-v1'
CODE_HASH=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
NUM=r'\(?-?(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3}|\d+)(?:\.\d+)?\)?'
LABELS={'revenue':r'revenue from operations|net sales',
        'da':r'depreciation and amortisation(?: expense)?|depreciation and amortization(?: expense)?',
        'interest':r'finance costs?', 'assets':r'total assets',
        'liabilities':r'total liabilities',
        'cfo':r'net cash (?:generated from|from|provided by|used in) operating activities'}
DATE=r'(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(20\d{2})'


def parse_page(text):
    normalized=re.sub(r'\bY\s+ear\b','Year',text,flags=re.I)
    titles=re.findall(r'^\s*(consolidated|standalone)\s+(statement of profit and loss|balance sheet|statement of cash flows?|cash flow statement)\b',normalized,re.I|re.M)
    scopes={x[0].casefold() for x in titles}
    if len(scopes)!=1:
        return [],'No unambiguous primary-statement heading on this page.'
    if re.search(r'\b(?:fifteen|15|eighteen|18)\s*months?\b',normalized,re.I):
        return [],'Nonstandard reporting length needs explicit manual period reconciliation.'
    dates=[]
    for match in re.finditer(r'(?:year ended|as at)\s+'+DATE,normalized,re.I):
        try:
            month=next(i for i,name in enumerate(calendar.month_name) if name and name.casefold()==match[2].casefold())
            end=date(int(match[3]),month,int(match[1]))
        except (ValueError,StopIteration):
            continue
        if end not in dates:dates.append(end)
    if len(dates)!=2 or dates[0]<=dates[1] or (dates[0].month,dates[0].day)!=(dates[1].month,dates[1].day) or not 360<=(dates[0]-dates[1]).days<=370:
        return [],'Two ordered comparable annual column dates could not be established.'
    units=set(re.findall(r'\b(?:in|amounts in)\s+(?:(?:INR|Rs\.?|₹|H)\s+)?(crores?|lakhs?|millions?)\b',normalized,re.I))
    scales={u.casefold().rstrip('s') for u in units}
    if len(scales)!=1:
        return [],'Missing or conflicting statement scale.'
    scale=next(iter(scales))
    if scale not in ('crore','lakh'):
        return [],'This parser does not promote million-unit statements.'
    currency='INR' if re.search(r'\bINR\b|\bRs\.|₹|Indian rupees',normalized,re.I) else None
    kind=titles[0][1].casefold()
    stock=kind=='balance sheet'
    operations=None;found=[]
    for original in text.splitlines():
        heading=' '.join(original.upper().split())
        if heading=='CONTINUING OPERATIONS':operations='continuing'
        elif heading=='DISCONTINUED OPERATIONS':operations='discontinued'
        row=re.fullmatch(r'\s*(.*?)\s{2,}('+NUM+r')\s{2,}('+NUM+r')\s*',original)
        if not row or operations=='discontinued':continue
        if any(len(token)>40 or token.startswith('(')!=token.endswith(')') or token.startswith('(-') for token in (row[2],row[3])):continue
        label=re.sub(r'\s+\d+[A-Z]?\s*$','',row[1]).strip()
        metric=next((m for m,p in LABELS.items() if re.fullmatch(p,label,re.I)),None)
        if not metric or stock!=(metric in ('assets','liabilities')):continue
        if metric=='cfo' and 'cash' not in kind:continue
        for index,end in enumerate(dates):
            amount=row[index+2].replace(',','')
            if amount.startswith('('):amount='-'+amount[1:-1]
            start=None
            if not stock:
                try:start=end.replace(year=end.year-1)+timedelta(days=1)
                except ValueError:start=date(end.year-1,2,28)+timedelta(days=1)
            found.append({'metric':metric,'value':str(Decimal(amount)),'scale':scale,'currency':currency,
                'period_start':start.isoformat() if start else None,'period_end':end.isoformat(),
                'accounting_scope':next(iter(scopes)),'operations_scope':operations,
                'source_quote':original.strip(),'definition':label,
                'period_basis':'Balance at explicit closing date' if stock else 'Proposed 12-month period from annual heading; reviewer must confirm reporting length',
                'checks':{'primary_statement_heading':True,'two_column_dates':True,'explicit_scale':True,
                          'currency_explicit':currency is not None,'operations_scope_explicit':operations is not None},
                'limitations':['Human review required before valuation intake.']+
                    ([] if currency else ['Currency is not explicit in extracted text.'])+
                    ([] if operations else ['Operating scope needs confirmation.'])+
                    (['Reported/restated periods and reporting length need confirmation.'] if not stock else [])})
    # A repeated metric can mean adjacent tables or multiple accounting bases.
    keys={}
    for item in found:keys.setdefault((item['metric'],item['period_end']),[]).append(item)
    return [items[0] for items in keys.values() if len(items)==1], 'Two-column annual parser; other rows/layouts require further review.'


def _schema_available():
    return bool(storage.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='statement_candidates'"))


def scan(company,fingerprints=None):
    if not _schema_available():return {'status':'migration_required','candidates_added':0}
    for old in storage.rows("SELECT id,candidate_json FROM statement_candidates WHERE company=? AND status='pending'",(company,)):
        if json.loads(old['candidate_json']).get('parser_sha256')!=CODE_HASH:
            with storage.database() as db:db.execute("UPDATE statement_candidates SET status='stale' WHERE id=? AND status='pending'",(old['id'],))
    docs=storage.rows('SELECT DISTINCT d.*,l.relative_path FROM documents d JOIN library_documents l ON l.document_id=d.id WHERE l.company=?',(company,))
    added=parsed=skipped=0;issues=[]
    for doc in docs:
        path=(library.root_folder()/doc['relative_path']).resolve()
        digest=(fingerprints or {}).get(doc['relative_path'])
        if digest is None and path.is_file() and path.is_relative_to(library.root_folder()):
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if not path.is_relative_to(library.root_folder()) or not path.is_file() or digest!=doc['sha256']:
            issues.append({'document_id':doc['id'],'reason':'Original file changed or is missing.'})
            with storage.database() as db:db.execute("UPDATE statement_candidates SET status='stale' WHERE company=? AND document_id=?",(company,doc['id']))
            continue
        cached=storage.rows('SELECT result_json FROM statement_intake_documents WHERE company=? AND document_id=? AND parser_version=? AND source_sha256=?',(company,doc['id'],CODE_HASH,doc['sha256']))
        if cached:skipped+=1;continue
        count=0;reasons={}
        for passage in storage.rows('SELECT * FROM passages WHERE document_id=? ORDER BY pdf_page',(doc['id'],)):
            items,reason=parse_page(passage['text']);reasons[reason]=reasons.get(reason,0)+1
            for item in items:
                candidate={**item,'company':company,'document_id':doc['id'],'passage_id':passage['id'],
                    'source_file':doc['relative_path'],'source_page':str(passage['pdf_page']),
                    'source_url':doc['original_url'],'source_sha256':doc['sha256'],'source_date':doc['publication_date'],
                    'parser_version':VERSION,'parser_sha256':CODE_HASH,
                    'verification_status':'extracted_requires_review','source_link':f"/documents/{doc['id']}/original#page={passage['pdf_page']}"}
                cid=hashlib.sha256(json.dumps(candidate,sort_keys=True).encode()).hexdigest()
                with storage.database() as db:
                    change=db.execute("INSERT OR IGNORE INTO statement_candidates(id,company,document_id,passage_id,candidate_json,status,created_at) VALUES(?,?,?,?,?,'pending',?)",(cid,company,doc['id'],passage['id'],json.dumps(candidate),storage.now())).rowcount
                added+=change;count+=1
        result={'candidates':count,'page_outcomes':reasons}
        with storage.database() as db:db.execute('INSERT OR REPLACE INTO statement_intake_documents VALUES(?,?,?,?,?,?)',(company,doc['id'],doc['sha256'],CODE_HASH,storage.now(),json.dumps(result)))
        parsed+=1
    return {'status':'scanned','documents_scanned':parsed,'unchanged_documents_skipped':skipped,'candidates_added':added,'issues':issues,
            'verification':'Exact source rows extracted; valuation inputs remain unchanged until recorded review.'}


def candidates(company):
    rows=storage.rows('SELECT * FROM statement_candidates WHERE company=? ORDER BY created_at DESC,id',(company,))
    return [{'id':r['id'],'status':r['status'],'review_note':r['review_note'],'reviewed_at':r['reviewed_at'],**json.loads(r['candidate_json'])} for r in rows]


def review(cid,action,note,operations_scope=None,source_date=None,currency=None,confirm_period=False):
    if action not in ('approve','reject'):raise ValueError('Choose approve or reject.')
    if len(note.strip())<20:raise ValueError('Record a meaningful review explanation.')
    rows=storage.rows('SELECT * FROM statement_candidates WHERE id=?',(cid,))
    if not rows:raise ValueError('Candidate not found.')
    row=rows[0];item=json.loads(row['candidate_json'])
    if item['parser_sha256']!=CODE_HASH:raise ValueError('Parser changed; rescan the source before review.')
    path=(library.root_folder()/item['source_file']).resolve()
    if not path.is_relative_to(library.root_folder()) or not path.is_file():raise ValueError('Original source is unavailable.')
    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    if sha!=item['source_sha256']:raise ValueError('Original source changed; refresh and review again.')
    if row['status'] in ('stale','rejected'):raise ValueError('This candidate is not eligible for approval.')
    if row['status']=='approved':
        if action!='approve':raise ValueError('An approved input requires a separate reconciliation; it cannot be silently removed.')
        return {'status':'approved','library_record_id':row['library_record_id'],'already_reviewed':True}
    if action=='reject':
        with storage.database() as db:
            if not db.execute("UPDATE statement_candidates SET status='rejected',reviewed_at=?,review_note=? WHERE id=? AND status='pending'",(storage.now(),note,cid)).rowcount:
                raise ValueError('The review status changed; reload the candidate.')
        return {'status':'rejected'}
    if action!='approve':raise ValueError('Choose approve or reject.')
    passage=storage.rows('SELECT text FROM passages WHERE id=? AND document_id=?',(item['passage_id'],item['document_id']))
    if not passage or item['source_quote'] not in passage[0]['text']:raise ValueError('Source quotation could not be revalidated.')
    scope=item['operations_scope'] or operations_scope
    cur=item['currency'] or currency
    if scope not in ('continuing','total') or cur!='INR' or not source_date or source_date>storage.today_ist():
        raise ValueError('Confirm operating scope, INR currency and actual publication date before approval.')
    if not confirm_period:raise ValueError('Explicitly confirm the proposed reporting period and column mapping.')
    if item['source_date'] and source_date.isoformat()!=item['source_date']:raise ValueError('Publication date conflicts with the recorded document date.')
    record=FinancialRecord.model_validate({'company':item['company'],'metric':item['metric'],'value':item['value'],
        'unit':'INR_'+item['scale'],'currency':'INR','period_start':item['period_start'],'period_end':item['period_end'],
        'accounting_scope':item['accounting_scope'],'operations_scope':scope,'segment':'group',
        'definition':item['definition'],'source_type':'historical','source_url':item['source_url'],
        'source_file':item['source_file'],'source_page':item['source_page'],'source_date':source_date,
        'review_status':'user_verified','source_sha256':sha,'source_quote':item['source_quote'],
        'review_note':'Intake reviewed: '+note})
    if record.period_end>storage.today_ist():raise ValueError('Future reporting periods are not eligible.')
    if record.source_date<record.period_end:raise ValueError('Publication date precedes the reporting period end.')
    factor={'INR_crore':Decimal(10000000),'INR_lakh':Decimal(100000)}
    payload=record.model_dump(mode='json');rid=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    with storage.database() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT status,library_record_id FROM statement_candidates WHERE id=?',(cid,)).fetchone()
        if current['status']=='approved':return {'status':'approved','library_record_id':current['library_record_id'],'already_reviewed':True}
        if current['status']!='pending':raise ValueError('The review status changed; reload the candidate.')
        for oldrow in db.execute('SELECT record_json FROM library_records WHERE company=?',(record.company,)).fetchall():
            old=FinancialRecord.model_validate_json(oldrow['record_json'])
            if old.review_status not in ('user_verified','source_verified'):continue
            if (old.metric,old.period_start,old.period_end,old.accounting_scope,old.operations_scope)==(record.metric,record.period_start,record.period_end,record.accounting_scope,record.operations_scope):
                if Decimal(old.value)*factor.get(old.unit,1)!=Decimal(record.value)*factor.get(record.unit,1):
                    raise ValueError('Conflicts with a reviewed financial input. Reconcile the restatement or definition first.')
        db.execute('INSERT OR IGNORE INTO library_records VALUES(?,?,?,?,?)',(rid,record.company,json.dumps(payload),sha,storage.now()))
        db.execute("UPDATE statement_candidates SET status='approved',reviewed_at=?,review_note=?,library_record_id=? WHERE id=?",(storage.now(),note,rid,cid))
    return {'status':'approved','library_record_id':rid,'verification':'User-reviewed; source hash and quotation checked; no existing inputs overwritten.'}
