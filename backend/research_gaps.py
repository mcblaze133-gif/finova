"""Model-independent financial questions and bounded evidence-gap retrieval.

Reported numbers remain Excel outputs. Search hits and lexical matches never
become corroborated claims, peer multiples, dates or forecast assumptions.
"""
import asyncio
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
import httpx
from backend import documents, investigation, storage
from backend.companies import resolve

TOPICS = (
    ('Demand and pricing', 'volume pricing realisation premiumisation distribution',
     'Separate underlying volume from price/mix, acquisitions and distribution changes.'),
    ('Margin sustainability', 'margin raw material commodity advertising packaging',
     'Reconcile margin changes with input costs, mix, pricing and brand investment.'),
    ('Cash backing and working capital', 'cash flow inventory inventories receivables payables working capital',
     'Reconcile profit with cash and distinguish recurring cash generation from timing.'),
    ('Reinvestment and capital allocation', 'capital expenditure capex capacity acquisition dividend',
     'Test whether lower spending reflects completed capacity or deferred reinvestment.'),
    ('Segments and competitive position', 'segment category market share competition brands geography',
     'Match categories and reporting scope before inferring market-share gains or a moat.'),
    ('Management and governance', 'related party auditor remuneration governance contingent litigation',
     'Read qualifications, related-party dealings and contingent claims; absence of a match is not a clean bill of health.'),
    ('Management promises versus delivery', 'guidance outlook target expect expansion growth',
     'Match a dated prior promise to the same metric and period in subsequent actuals.'),
    ('Peer and transaction evidence', 'peer comparable acquisition consideration transaction valuation',
     'Require category-matched dated prices, normalised earnings and ownership/control terms; a quoted multiple is insufficient.'),
)
ANCHORS = (
    r'\bvolume\b|price.mix|realisations?|distribution',
    r'EBITDA|operating margin|gross margin|commodit|raw materials?|advertising',
    r'operating cash flows?|cash generated from operations|cash flows? from operating|working capital|inventor(?:y|ies)|trade receivables|trade payables',
    r'capital expenditure|\bcapex\b|new capacity|capacity expansion|purchase.{0,60}property|payment.{0,60}property',
    r'segment revenue|segment results|market share|categor(?:y|ies)|competitive',
    r'related.part|contingent liabilit|litigation|remuneration|qualified opinion',
    r'\b(?:expect\w*|guidance|target\w*|outlook|anticipat\w*)\b.{0,160}(?:\d+(?:\.\d+)?\s*%|FY\s*\d{2,4}|20\d{2}|next year|next quarter)',
    r'acquisition.{0,100}(?:consideration|crore|million|billion)|enterprise value|valuation multiple|control premium',
)

def numeric(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def subject_matches(text,profile):
    normal=lambda s:unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().casefold()
    tokens=[t for t in re.findall('[a-z0-9]+',normal(profile.legal_name)) if t not in ('limited','ltd')]
    # Brand prefixes such as "Tata" and scattered generic words do not identify
    # an issuer. Require its full legal identity, allowing accents/spacing.
    return bool(tokens) and bool(re.search(r'\b'+r'[\s,.\-]+'.join(re.escape(t) for t in tokens)+r'\b',normal(text)))

def comparable(a,b):
    return (a.get('scope') == b.get('scope') and a.get('scope') is not None
            and abs(a.get('duration_days',0)-b.get('duration_days',0))<=2
            and 300<=a.get('duration_days',0)<=370 and 300<=b.get('duration_days',0)<=370)

def signals(history):
    """Compare saved Excel diagnostics; do not recalculate valuation or ratios."""
    periods=history.get('periods',[]);ds=history.get('excel_diagnostics',[])
    if len(periods)<2 or len(ds)!=len(periods) or not comparable(periods[-2],periods[-1]):return []
    a,b=ds[-2:];pa,pb=periods[-2:];out=[]
    def add(title,observation,keys,alternative,test,use,query):
        out.append(dict(title=title,observation=observation,status='Financial observation; causal hypothesis unconfirmed',
            comparison=[{'period':p['label'],**{k:d.get(k) for k in keys}} for p,d in ((pa,a),(pb,b))],
            alternative=alternative,falsification=test,investor_use=use,query=query,
            evidence_strength='Reported figures with source links; independent causal corroboration not established'))
    if all(numeric(d.get(k)) for d in (a,b) for k in ('cash_after_capex_crore','cash_conversion')) and b['cash_after_capex_crore']>a['cash_after_capex_crore'] and b['cash_conversion']<a['cash_conversion']:
        add('More cash after capex, weaker cash backing of profit',
            'Cash remaining after capex increased while operating cash flow / parent profit declined.',
            ['cash_after_capex_crore','cash_conversion'],
            'Lower capital spending or timing of working-capital payments could explain the improvement without stronger recurring cash economics.',
            'A same-scope cash-flow bridge showing stronger recurring operating cash generation after normalised maintenance investment would weaken this concern.',
            'Do not raise sustainable payout or terminal cash-flow assumptions solely because cash after capex rose.',
            'cash flow capital expenditure working capital capacity')
    if all(numeric(d.get('ebitda_margin')) for d in (a,b)):
        peak=max((d['ebitda_margin'] for p,d in zip(periods,ds) if comparable(p,pb) and numeric(d.get('ebitda_margin'))),default=b['ebitda_margin'])
        if b['ebitda_margin']>a['ebitda_margin'] and b['ebitda_margin']<peak:
            add('Margin recovery has not regained the comparable historical peak',
                'The latest operating EBITDA margin improved, but remains below an earlier comparable reported margin.',
                ['ebitda_margin'], 'Commodity relief or mix may explain the recovery rather than durable pricing power.',
                'Sustained volume-led growth and a sourced cost/mix bridge through another input-cost cycle would support a structural improvement.',
                'Stress the persistence of margin recovery instead of extrapolating the latest improvement indefinitely.',
                'margin recovery commodity pricing volume mix advertising')
    if numeric(b.get('revenue_growth')):
        add('Reported sales growth does not identify its operating source',
            'Matched-period revenue growth is available; the number alone cannot separate volume, price/mix and acquired revenue.',
            ['revenue_growth'], 'Pricing, acquisitions or scope changes may contribute even when headline growth looks healthy.',
            'A sourced volume/price/mix and acquisition reconciliation matching the reported period would resolve the ambiguity.',
            'Use the operating bridge to test revenue forecasts and the growth premium in selected multiples.',
            'volume growth pricing mix acquisition revenue')
    return out

def excerpt(row,query,anchor=None):
    terms=re.findall(r'[a-z]{3,}',query.casefold())
    text=' '.join(row['text'].split());positions=[text.casefold().find(t) for t in terms if t in text.casefold()]
    match=re.search(anchor,text,re.I) if anchor else None
    start=max(0,(match.start() if match else min(positions or [0]))-100);quote=text[start:start+760]
    indexed=text.startswith('Reviewed financial record index for a scanned PDF page.')
    if indexed:quote='Reviewed record index - not OCR or a verbatim page transcription: '+quote
    return {'document_id':row['document_id'],'passage_id':row['id'],'page':row['pdf_page'],
        'title':row.get('title','Source document'),'quote':quote,'sha256':row.get('sha256'),
        'publication_date':row.get('publication_date'),
        'url':f'/documents/{row["document_id"]}/original#page={row["pdf_page"]}',
        'original_url':row.get('original_url'),'text_origin':'reviewed_record_index' if indexed else 'pdf_text',
        'evidence_status':'Whitespace-normalised retrieved passage, not a verified answer to the research question'}

def local_dossier(payload,rows):
    topics=[]
    for index,(title,query,question) in enumerate(TOPICS):
        # Require multiple different topic terms, not a stray mention of "growth".
        terms=query.split()
        eligible=[r for r in rows if sum(t in r['text'].casefold() for t in terms)>=2
                  and re.search(ANCHORS[index],' '.join(r['text'].split()),re.I)]
        if index in (0,1,2,3,4,6,7):
            eligible=[r for r in eligible if not re.search(r'fair value hierarchy|expected credit losses|measurement of financial instruments',r['text'],re.I)]
        if index==2:
            eligible=[r for r in eligible if not re.search(r'financial instruments|fair value of|valuation techniques|contractual cash flows',r['text'],re.I)]
            cash_statements=[r for r in eligible if re.search(r'cash flow statement|statement of cash flows|cash flows from operating activities|net cash (?:generated|from).*operating', ' '.join(r['text'].split()),re.I)]
            if cash_statements:eligible=cash_statements
        if index==3:
            eligible=[r for r in eligible if not re.search(r'recognition and measurement|deemed cost',r['text'],re.I)]
        selected=investigation.search_prepared(eligible,query,3)
        topics.append({'topic':title,'question':question,'query':query,
            'status':'Relevant passages located; interpretation and corroboration required' if selected else 'No sufficiently relevant extract located',
            'excerpts':[excerpt(r,query,ANCHORS[index]) for r in selected]})
    return {'checked_at':storage.now(),'signals':signals(payload.get('history',{})), 'topics':topics,
        'retrieval_audit':[], 'policy':'A matched passage is not a finding. Retrieved dates remain attributed. No missing value is estimated or promoted into Excel.',
        'unresolved':['Independent confirmation of causal explanations', 'Normalised, category-matched forward peer and transaction inputs'],
        'scope':'All available compact-pack periods searched; source dates and reporting bases must be reconciled before a conclusion.'}

def report_coverage(payload):
    """Measure completed, partial and missing work separately from discovery."""
    raw=payload.get('research',{})
    sections={s['topic']:s for s in raw.get('sector_sections',[]) if s.get('statements')}
    assessments={s['topic']:s for s in raw.get('section_analysis',{}).get('areas',[])}
    periods=payload.get('history',{}).get('periods',[])
    needed=('revenue','ebitda','net_income','cfo','assets','liabilities','debt','cash')
    missing=[key for key in needed if not periods or not numeric(periods[-1].get('values',{}).get(key))]
    def row(area,status,detail):
        return {'area':area,'status':status,'covered':status=='complete','next_action':detail}
    rows=[row('Financial statements','complete' if not missing else 'partial' if periods else 'missing',
        'Historical statements available; latest-period gaps: '+', '.join(missing) if missing and periods else 'Historical actuals and source links available; scope qualifications still apply.' if periods else 'No validated historical statements available.'),
        row('Conditional valuation','complete' if payload.get('valuation') else 'missing','Editable conditional scenarios; assumptions require review.' if payload.get('valuation') else 'Build and validate the Excel model.')]
    for topic in ('Business and products','Demand, volume and pricing','Costs and profitability','Segments and geography',
                  'Competition and economic moat','Management and governance','Capital allocation','Risks and catalysts','Macro and commodity exposure'):
        assessment=assessments.get(topic)
        status=assessment['status'] if assessment else 'partial' if topic in sections else 'missing'
        detail=assessment.get('review_reason','') if assessment else 'Cited narrative available; dedicated section review not recorded.' if topic in sections else 'No validated topic assessment; retrieve company-specific supporting and contrary evidence.'
        if assessment and assessment.get('gaps'):detail+=' Remaining: '+'; '.join(assessment['gaps'])
        rows.append(row(topic,status,detail))
    news=payload.get('news') or {}; news_result=news.get('result') or {}
    state='complete' if news.get('status')=='assessed' else 'partial' if news_result.get('events') or news.get('checked_at') else 'missing'
    rows.append(row('Current developments',state,('Current events assessed; original-source verification or exposure gaps remain.' if news_result.get('events') else 'Current check attempted; no completed source-assessed event is available.') if state=='partial' else 'Source-assessed current developments available.' if state=='complete' else 'No current news assessment available.'))
    admitted=bool(raw.get('discovery_checks',{}).get('admitted'))
    rows.append(row('Corroborated discovery','complete' if admitted else 'partial' if raw.get('candidate_discovery') or raw.get('hypotheses') else 'missing',
        'Evidence-gated discovery available.' if admitted else 'No confirmed discovery: independent origins, linked calculation, dated timeline and opposing review must pass.'))
    return {'complete':all(r['covered'] for r in rows),'areas':rows,
            'meaning':'Complete means the stated work passed its scoped checks, not that causal claims or forecasts are proven. Partial identifies usable work with remaining limitations; missing means no validated assessment.'}


def parse_search_rss(content):
    if len(content)>1_000_000 or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError('Unsupported search response')
    root=ET.fromstring(content);hits=[];seen=set()
    for item in root.findall('./channel/item'):
        url=item.findtext('link','');title=item.findtext('title','Public search lead')
        try:
            p=urlsplit(url)
            if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443) or url in seen:continue
        except ValueError:continue
        seen.add(url);hits.append({'url':url,'title':title})
    return hits[:5]

async def search_with_fallback(query,company,audit):
    audit['search_providers']=[]
    try:
        hits=await investigation.public_search(query,company)
        audit['search_providers'].append({'provider':'GDELT','status':'leads_returned' if hits else 'no_leads'})
        if hits:return hits
    except Exception:
        audit['search_providers'].append({'provider':'GDELT','status':'unavailable'})
    # Public RSS search needs neither an API key nor paid credits. Its hits are
    # still only leads; original fetching applies DNS/robots/redirect safeguards.
    try:
        async with httpx.AsyncClient(timeout=10,trust_env=False,follow_redirects=False) as client:
            response=await client.get('https://www.bing.com/search',params={'q':company+' '+query,'format':'rss'})
            response.raise_for_status();hits=parse_search_rss(response.content)
        audit['search_providers'].append({'provider':'Bing public RSS','status':'leads_returned' if hits else 'no_leads'})
        return hits
    except Exception:
        audit['search_providers'].append({'provider':'Bing public RSS','status':'unavailable'})
        return []

async def investigate(payload,*,live=True):
    """Runs even if the generative provider failed. No paid API or model calls."""
    company=payload['company_id'];profile=resolve(company)
    try:
        rows,proof=await asyncio.to_thread(investigation.prepared_passages,company)
    except (ValueError,OSError):
        return {'signals':signals(payload.get('history',{})),'topics':[], 'retrieval_audit':[],
                'unresolved':['Compact evidence could not be validated; no substitute historical narrative was used.']}
    dossier=local_dossier(payload,rows);dossier['pack_proof']=proof
    if not live:return dossier
    query=dossier['signals'][0]['query'] if dossier['signals'] else TOPICS[0][1]
    queries=[('competitive_evidence','market share competition categories distribution industry'),
             ('support',query),('challenge','capital expenditure working capital temporary timing risks'),
             ('peer_gap','peer valuation forward earnings EBITDA comparable')]
    async def retrieve():
        for side,q in queries:
            audit={'side':side,'query':profile.legal_name+' '+q,'status':'not_started','originals':[]}
            dossier['retrieval_audit'].append(audit)
            try:
                hits=await search_with_fallback(q,profile.legal_name,audit)
                audit['status']='Search returned leads only' if hits else 'No usable search leads; evidence gap remains'
                for hit in hits[:2]:
                    try:
                        host=urlsplit(hit['url']).hostname
                        if not host or host in ('news.google.com','bing.com','www.bing.com'):continue
                        async with asyncio.timeout(12):
                            raw,kind,url=await documents.Fetcher([host]).fetch(hit['url'])
                            pages,_=await asyncio.to_thread(documents.extract,raw,kind)
                        text=' '.join(pages).casefold()
                        if not subject_matches(text,profile) or sum(t in text for t in q.split())<2:
                            raise ValueError('Unrelated search original')
                        doc_id=await asyncio.to_thread(documents.save_document,company,url,hit['title'],raw,kind)
                        found=[r for r in documents.search(company,q,24) if r['document_id']==doc_id][:2]
                        if not found:raise ValueError('No relevant original passage')
                        audit['originals'].append({'url':url,'status':'original_read','excerpts':[excerpt(r,q) for r in found]})
                        break
                    except Exception:
                        audit['originals'].append({'url':hit['url'],'status':'unavailable_or_irrelevant'})
            except Exception:
                audit['status']='Search unavailable; evidence gap remains'
    try:
        async with asyncio.timeout(65):await retrieve()
    except TimeoutError:
        dossier['unresolved'].append('Targeted public retrieval reached its 65-second limit; unfinished searches remain unresolved.')
    dossier['checked_at']=storage.now()
    return dossier
