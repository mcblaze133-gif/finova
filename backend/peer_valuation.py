"""Reviewed peer inputs and suitability; Excel owns business calculations."""
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from backend import storage


def evidence(ref,hashes=None):
    found=storage.rows('SELECT d.id,d.company,d.local_path,d.sha256,d.original_url,d.title,p.text,p.pdf_page FROM documents d JOIN passages p ON p.document_id=d.id WHERE d.id=? AND p.pdf_page=?',(ref['document_id'],ref['page']))
    if len(found)!=1:raise ValueError('Peer source page missing or ambiguous.')
    row=found[0];path=(storage.PROJECT_DIR/row['local_path']).resolve()
    if not path.is_relative_to((storage.DATA_DIR/'raw').resolve()):raise ValueError('Peer source path outside archive.')
    hashes={} if hashes is None else hashes
    if path not in hashes:
        with path.open('rb') as f:hashes[path]=hashlib.file_digest(f,'sha256').hexdigest()
    digest=hashes[path]
    normal=lambda text:' '.join(text.casefold().split())
    if digest!=row['sha256'] or digest!=ref['sha256'] or not ref.get('quote') or normal(ref['quote']) not in normal(row['text']):
        raise ValueError('Peer source hash or exact quotation does not match.')
    return {'title':row['title'],'url':f'/documents/{row["id"]}/original#page={row["pdf_page"]}',
            'publisher_url':row['original_url'],'page':row['pdf_page'],'sha256':digest,'quote':ref['quote']}


def build(company):
    path=storage.PROJECT_DIR/'data/peer-reviews.json'
    if not path.exists():return None
    review=json.loads(path.read_text(encoding='utf-8'));on_date=date.fromisoformat(review['price_date'])
    if on_date>storage.today_ist():raise ValueError('Peer price date is in the future.')
    policy=review.get('policies',{}).get(company)
    if not policy:return None
    ids=[item['company_id'] for item in review['companies']]
    if len(ids)!=len(set(ids)) or company in policy['included'] or not set(policy['included']).issubset(ids):
        raise ValueError('Invalid peer selection or duplicate company.')
    periods={(item['period_start'],item['period_end']) for item in review['companies']}
    if len(periods)!=1:raise ValueError('Mixed earnings periods rejected.')
    companies=[];hashes={}
    for item in review['companies']:
        start,end=map(date.fromisoformat,(item['period_start'],item['period_end']))
        if not 330<=(end-start).days+1<=370 or end>on_date or item['accounting_scope']!='consolidated':
            raise ValueError('Peer period or reporting basis is not comparable.')
        refs=[evidence(ref,hashes) for ref in item['evidence']]
        if not refs:raise ValueError('Peer review has no source evidence.')
        values=item['values']
        allocation=item.get('owner_allocation')
        if type(allocation) not in (int,float) or not math.isfinite(allocation) or not 0<=allocation<=1:
            raise ValueError('Invalid analyst ownership allocation.')
        for key,value in values.items():
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value)):
                raise ValueError('Peer inputs must be finite numeric values or explicit missing values.')
        if item['price_date']!=review['price_date']:raise ValueError('Mixed peer price dates rejected.')
        if values.get('market_cap',0)<=0 or values.get('revenue',0)<=0:raise ValueError('Missing market capitalisation or revenue.')
        # Exchange market capitalisation is rounded to 0.01 crore. A stale
        # pre-bonus/pre-allotment count cannot silently enter per-share outputs.
        if values.get('shares') is not None:
            if values['shares']<=0 or values.get('price',0)<=0 or abs(values['market_cap']-values['price']*values['shares'])>50001:
                raise ValueError('Basic share count does not reconcile with the dated exchange snapshot.')
        selected=item['company_id'] in policy['included'] and item['company_id']!=company
        companies.append({**item,'sources':refs,'included':selected,'subject':item['company_id']==company,
                          'selection_reason':policy['included'].get(item['company_id']) if selected else 'Subject company excluded from its own peer set.' if item['company_id']==company else policy.get('excluded',{}).get(item['company_id'],'Different operating/category mix; not selected.')})
    if sum(bool(c['subject']) for c in companies)!=1:raise ValueError('Peer review subject must occur exactly once.')
    return {'price_date':review['price_date'],'earnings_period':'FY2026, year ended 31 March 2026',
            'companies':companies,'policy':policy,'reviewed_at':review['reviewed_at'],
            'meaning':'Conditional historical-earnings cross-check. Inputs were transcribed and reviewed against issuer filings and exchange captures; archive hashes and exact quotations are checked automatically. This is not an independent audit. Tax/ownership allocation for exceptional adjustments is an explicit analyst estimate. Book enterprise-value bridges retain their separately stated dates. No peer is approved solely because it is FMCG.'}
