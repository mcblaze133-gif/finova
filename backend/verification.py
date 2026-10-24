"""Explain performed checks without claiming universal authenticity or accuracy."""
import hashlib
import json
from pathlib import Path
from backend import storage,library


def render(audit,company_name):
    from html import escape
    from urllib.parse import urlsplit
    esc=lambda x:escape(str(x or ''),quote=True)
    rows=[]
    for item in audit['items']:
        source=item['source'];checks=item['checks'];url=source['url']
        link=f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">Original source</a>' if urlsplit(url).scheme=='https' else 'Original retained in local library'
        archived=source.get('archived_url') or ''
        if __import__('re').fullmatch(r'/documents/[0-9]+/original#page=[0-9]+',archived):link+=f'  &middot;  <a href="{esc(archived)}" target="_blank" rel="noopener noreferrer">Archived page</a>'
        rows.append(f'''<tr><td>{esc(item['metric'])}<br><small>{esc(item['period_end'])}<br>{esc(item['accounting_scope'])} / {esc(item['operations_scope'])}</small></td>
<td>{'File matches recorded hash' if checks['current_file_matches_recorded_hash'] else 'File-integrity check incomplete'}<br>{'Review recorded' if checks['review_recorded'] else 'Review explanation missing'}</td>
<td>{link}<br>{esc(source['file'])}<br>Page / row: {esc(source['page'])}<br>Source date: {esc(source['date'])}</td>
<td>{esc(checks['review_explanation'])}<details><summary>Recorded quotation and file identity</summary><p>{esc(source.get('quote'))}</p><small>Recorded SHA-256: {esc(source['sha256'])}</small></details></td></tr>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Verification register | Finova</title><style>
body{{font:15px/1.5 system-ui,sans-serif;color:#17334a;margin:0;background:#f2f6f7}}main{{max-width:1300px;margin:32px auto;padding:24px;background:white}}h1{{font-size:26px}}small{{color:#536672}}table{{width:100%;border-collapse:collapse;table-layout:fixed}}th{{background:#17334a;color:white;text-align:left}}th,td{{padding:12px;vertical-align:top;overflow-wrap:anywhere}}tr:nth-child(even){{background:#eff5f5}}th:nth-child(1){{width:16%}}th:nth-child(2){{width:20%}}th:nth-child(3){{width:24%}}a{{color:#147d73}}details{{margin-top:10px}}summary{{cursor:pointer;color:#147d73}}details p{{white-space:pre-wrap}}.table{{overflow-x:auto}}table{{min-width:750px}}
</style></head><body><main><h1>{esc(company_name)}: verification register</h1><p>Checks recorded {esc(audit['checked_at'])}. {audit['integrity_and_review_passed']} of {audit['input_records']} source-input records have matching file hashes and recorded review explanations.</p>
<p>File integrity, recorded review and independent corroboration are separate checks. This register records the checks performed and their limits. A matching file hash does not independently prove issuer authenticity or the correctness of a financial conclusion.</p>
<div class="table"><table><thead><tr><th>Input and period</th><th>Checks</th><th>Source evidence</th><th>How reviewed</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></main></body></html>'''


def build(company,inputs=None,news=None,workbook_path=None,workbook_sha256=None):
    records=inputs.get('sources',[]) if inputs is not None else [r.model_dump(mode='json') for r in library.company_records(company)]
    if inputs is not None and inputs.get('historical_statements',{}).get('periods'):
        wanted=set()
        for period in inputs['historical_statements']['periods']:
            for metric,refs in period.get('sources',{}).items():
                for ref in refs:wanted.add((metric,period['end'],period['accounting_scope'],period['operations_scope'],ref['file'],ref['sha256']))
        records=[*records,*[r.model_dump(mode='json') for r in library.company_records(company)
            if (r.metric,r.period_end.isoformat(),r.accounting_scope,r.operations_scope,r.source_file,r.source_sha256) in wanted]]
    records=list({json.dumps(r,sort_keys=True):r for r in records}.values())
    try:root=library.root_folder() if records else None
    except (OSError,ValueError,KeyError):root=None
    hashes={};items=[]
    documents={r['sha256']:r['id'] for r in storage.rows('SELECT id,sha256 FROM documents WHERE company=?',(company,))} if records else {}
    for r in records:
        path=(root/r['source_file']).resolve() if root else None
        if path not in hashes:
            digest=None
            if path and path.is_relative_to(root) and path.is_file():
                with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            hashes[path]=digest
        integrity=bool(r.get('source_sha256') and hashes[path]==r['source_sha256'])
        reviewed=r.get('review_status') in ('source_verified','user_verified') and bool(r.get('review_note'))
        archived=f"/documents/{documents[r['source_sha256']]}/original#page={str(r['source_page']).split(',')[0]}" if r.get('source_sha256') in documents else None
        items.append({'metric':r['metric'],'period_end':r['period_end'],'unit':r['unit'],
            'accounting_scope':r['accounting_scope'],'operations_scope':r['operations_scope'],
            'status':'review_recorded_integrity_checked' if reviewed and integrity else 'verification_incomplete',
            'source':{'file':r['source_file'],'page':r['source_page'],'url':r['source_url'],'date':r['source_date'],'sha256':r.get('source_sha256'),'quote':r.get('source_quote'),'archived_url':archived},
            'checks':{'current_file_matches_recorded_hash':integrity,'review_recorded':reviewed,
                      'review_type':r.get('review_status'),'review_explanation':r.get('review_note'),
                      'source_quote_recorded':bool(r.get('source_quote'))},
            'meaning':'File integrity and recorded source review. This does not independently prove issuer authenticity or economic interpretation.'})
    complete=sum(x['status']=='review_recorded_integrity_checked' for x in items)
    original_status=[]
    if news:
        original_status=(news.get('result') or {}).get('primary_source_coverage',[])
    matched=None
    if workbook_path and workbook_sha256:
        p=Path(workbook_path)
        if p.is_file():
            with p.open('rb') as stream:matched=hashlib.file_digest(stream,'sha256').hexdigest()==workbook_sha256
        else:matched=False
    components=[
        {'system':'Historical inputs','status':'Checks recorded' if items and complete==len(items) else 'Incomplete',
         'how':f'{complete} of {len(items)} input records have a recorded review and matching current source hash. Periods, units and reporting bases accompany each input.'},
        {'system':'Source authenticity','status':'Independent authenticity not established',
         'how':'Source URLs, archived originals and page references provide traceability. A file hash proves consistency with the saved file, not that a document is authentic.'},
        {'system':'Current developments','status':(news or {}).get('status','Not checked in this audit'),
         'how':f'{sum(c.get("status")=="original_read" for c in original_status)} original-source checks recorded. Feed headlines and model interpretations remain separate from verified financial facts.'},
        {'system':'Assumptions','status':'Estimates, not verified actuals',
         'how':'Historical, external, management and analyst categories stay distinct. Sources, rationale and confidence remain in the assumption register.'},
        {'system':'Excel and report','status':'Workbook hash matched' if matched else 'Workbook hash mismatch' if matched is False else 'Not checked in this audit',
         'how':'The PDF binds a specific workbook hash. Saved formula values are used; native desktop Excel recalculation has not been independently verified.'},
        {'system':'Research conclusions','status':'Evidence-dependent',
         'how':'Citation checks, counterarguments and falsification conditions support review. Several company documents and model agreement do not establish independent corroboration.'}]
    return {'checked_at':storage.now(),'company':company,'input_records':len(items),'integrity_and_review_passed':complete,
            'items':items,'systems':components,'authenticity_claim':'No blanket authenticity or error-free accuracy claim.'}
