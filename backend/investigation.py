"""Question-directed evidence collection and conservative discovery admission.

Search results are leads. Only successfully retrieved originals enter the passage
catalog. Different domains are candidate origins, never proof of independence.
"""
import asyncio
import json
import re
import time
import httpx
from urllib.parse import urlencode, urlsplit
from backend import documents, storage
from backend.companies import resolve

SEARCH_LOCK=asyncio.Lock()
SEARCH_NEXT=0.0
SEARCH_BLOCKED_UNTIL=0.0

def read_selected_pdf_pages(company, rows):
    """Read current physical compact-PDF pages, not just a prior analysis JSON."""
    from pypdf import PdfReader
    from backend import evidence_packs
    import hashlib
    manifest=evidence_packs.read_manifest(company)
    path=evidence_packs.pack_root(company)/manifest['pdf']
    if evidence_packs.digest_file(path)!=manifest['artifact_hashes'][manifest['pdf']]:
        raise ValueError('The compact PDF changed during investigation. Refresh and rerun.')
    reader=PdfReader(path);proof=[]
    for row in rows:
        number=row.get('pack_page')
        if not isinstance(number,int) or not 1<=number<=len(reader.pages):raise ValueError('Invalid compact PDF page reference.')
        page=reader.pages[number-1]
        content=page.get_contents()
        proof.append({'pack_page':number,'original_page':row['pdf_page'],
                      'content_sha256':hashlib.sha256(content.get_data() if content else b'').hexdigest()})
    return {'read_at':storage.now(),'pages':proof,'policy':'Physical PDF pages re-read; question-directed excerpts, not an exhaustive page-by-page review.'}


def prepared_passages(company, cutoff=None):
    from backend import evidence_packs
    root=evidence_packs.pack_root(company).resolve()
    manifest=evidence_packs.read_manifest(company)
    if not manifest:raise ValueError('Prepare the company evidence pack before investigating.')
    if evidence_packs.source_fingerprints(company)!=manifest['source_fingerprints']:
        raise ValueError('Company sources changed. Refresh the compact evidence pack before reading it.')
    paths={}
    for key in ('pdf','pages'):
        path=(root/manifest[key]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or evidence_packs.digest_file(path)!=manifest['artifact_hashes'].get(manifest[key]):
            raise ValueError('The prepared evidence pack needs to be refreshed.')
        paths[key]=path
    pages=json.loads(paths['pages'].read_text(encoding='utf-8'))
    originals=storage.rows('SELECT p.id,p.document_id,p.pdf_page,d.company,d.title,d.original_url,d.publication_date,d.sha256,l.relative_path FROM passages p JOIN documents d ON d.id=p.document_id JOIN library_documents l ON l.document_id=d.id WHERE l.company=?',(company,))
    lookup={(r['relative_path'],r['pdf_page'],r['sha256']):r for r in originals}
    selected=[]
    for page in pages:
        row=lookup.get((page['source_file'],page['original_page'],page['source_sha256']))
        if row and (not cutoff or row['publication_date'] and row['publication_date']<=cutoff):
            selected.append(dict(row,text=page['text'],pack_page=page['pack_page'],
                                 document_kind=page.get('document_kind'),
                                 period_sort_hint_unverified=page.get('period_sort_hint_unverified')))
    if not selected:raise ValueError('The prepared evidence pack has no usable original-page references.')
    if not cutoff and len(selected)!=len(pages):
        raise ValueError('Some compact evidence pages have lost their original references. Refresh the pack before investigating.')
    return selected,{'signature':manifest['signature'],'selected_pages':len(selected),'pdf':manifest['pdf'],
                     'pdf_sha256':manifest['artifact_hashes'][manifest['pdf']],'read_at':storage.now()}


def search_prepared(rows, query, limit=4):
    terms=list(dict.fromkeys(re.findall(r'[\w-]{3,40}',query.casefold())))[:12]
    score=lambda row:sum(min(row['text'].casefold().count(t),10) for t in terms)
    ranked=sorted((r for r in rows if score(r)),key=score,reverse=True)
    return balance_prepared(ranked,limit)


def balance_prepared(ranked,limit):
    """Keep relevance order within each unverified period group."""
    if limit<=0:return []
    if limit==1:return ranked[:1]
    # Period hints only diversify retrieval. They never establish publication,
    # event dates, fiscal periods, or permission to calculate across scopes.
    def bucket(row):
        hint=row.get('period_sort_hint_unverified')
        return hint[0] if isinstance(hint,(tuple,list)) and hint and isinstance(hint[0],int) and 20<=hint[0]<=50 else 0
    groups={}
    for row in ranked:groups.setdefault(bucket(row),[]).append(row)
    selected=[]
    keys=sorted(groups,key=lambda y:(y==0,y))
    # When the budget is smaller than history, keep both earliest and latest
    # evidence instead of allowing a high-scoring recent PDF to monopolize it.
    if len(keys)>limit and limit>1:
        known=[year for year in keys if year]
        sample=known if len(known)>=limit else keys
        keys=[sample[round(i*(len(sample)-1)/(limit-1))] for i in range(limit)]
    for year in keys:
        if len(selected)>=limit:break
        selected.append(groups[year][0])
    used={r['id'] for r in selected}
    represented={r['document_id'] for r in selected}
    for row in ranked:
        if len(selected)>=limit:break
        if row['id'] not in used and row['document_id'] not in represented:
            selected.append(row);used.add(row['id']);represented.add(row['document_id'])
    for row in ranked:
        if len(selected)>=limit:break
        if row['id'] not in used:selected.append(row);used.add(row['id'])
    return selected


async def public_search(query, company=None):
    # Documented no-key news index API; unlike general search HTML, this endpoint
    # is intended for programmatic discovery. Original articles remain separate.
    stop={'the','and','from','with','that','this','rather','than','primarily','driven','limited','does','would','which','into','their','reported'}
    company_words=set(re.findall(r'[a-z]+',(company or '').casefold()))
    terms=list(dict.fromkeys(t for t in re.findall(r'[a-z]{4,}',query.casefold()) if t not in stop|company_words))[:8]
    if not terms:return []
    expression=('"'+company.removesuffix(' Limited').replace('"','')+'" ' if company else '')+'('+' OR '.join(terms)+')'
    url='https://api.gdeltproject.org/api/v2/doc/doc?'+urlencode({'query':expression[:350],'mode':'artlist','format':'json','maxrecords':5,'timespan':'3m','sort':'datedesc'})
    fetcher=documents.Fetcher(['api.gdeltproject.org'])
    global SEARCH_NEXT,SEARCH_BLOCKED_UNTIL
    async with SEARCH_LOCK:
        if time.monotonic()<SEARCH_BLOCKED_UNTIL:
            raise ValueError('Public discovery temporarily backed off; coverage incomplete.')
        if time.monotonic()<SEARCH_NEXT:
            await asyncio.sleep(SEARCH_NEXT-time.monotonic())
        SEARCH_NEXT=time.monotonic()+5
        try:
            data,_,_=await fetcher.fetch(url)
        except (httpx.RequestError, TimeoutError):
            # One unreachable discovery service must not consume every
            # hypothesis's time budget. This never supplies cached evidence:
            # callers retain an explicit independent-coverage gap. Other
            # company-news feeds and official-source checks are separate.
            SEARCH_BLOCKED_UNTIL=time.monotonic()+60
            raise ValueError('Public discovery connection unavailable; coverage incomplete.') from None
        except ValueError as exc:
            if '429' in str(exc):SEARCH_BLOCKED_UNTIL=time.monotonic()+60
            raise
    if len(data)>1_000_000 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Unsupported search response.')
    payload=json.loads(data)
    articles=payload.get('articles',[])
    if not isinstance(articles,list):raise ValueError('Invalid news index response.')
    return [{'url':i['url'],'title':i.get('title','Public article'),'index_seen_at':i.get('seendate')}
            for i in articles[:5] if isinstance(i,dict) and isinstance(i.get('url'),str)]


async def collect(profile, hypotheses, cutoff, live, run_id, prepared=None):
    found,audit={},[]
    for hypothesis in hypotheses[:2]:
        for side,query in (('support',hypothesis.search_terms),('challenge',hypothesis.alternative)):
            local=search_prepared(prepared,query,8) if prepared is not None else documents.search(profile.id,query,4,cutoff)
            for row in local:
                found[row['id']]=row
            entry={'question':hypothesis.question,'side':side,'query':query,'local_passages':[r['id'] for r in local],
                   'originals':[],'coverage':'local only'}
            audit.append(entry)
            if not live:
                continue
            try:
                async with asyncio.timeout(45):
                    results=await public_search(query,profile.legal_name)
                    entry['coverage']='public search returned leads; originals require retrieval'
                    for result in results[:2]:
                        try:
                            host=urlsplit(result['url']).hostname
                            if not host or host in ('www.bing.com','bing.com','news.google.com'):
                                continue
                            async with asyncio.timeout(15):
                                fetcher=documents.Fetcher([host])
                                raw,kind,original=await fetcher.fetch(result['url'])
                                text,_=await asyncio.to_thread(documents.extract,raw,kind)
                                # Reject search mismatches before cataloguing unrelated sources.
                                tokens=re.findall(r'[a-z]{4,}',query.casefold())[:8]
                                body=' '.join(text).casefold()
                                if not any(t in body for t in tokens):
                                    raise ValueError('Original does not contain research terms.')
                                doc_id=await asyncio.to_thread(documents.save_document,profile.id,original,result['title'],raw,kind)
                                selected=documents.search(profile.id,query,12,cutoff)
                                selected=[r for r in selected if r['document_id']==doc_id][:2]
                                for row in selected:found[row['id']]=row
                                entry['originals'].append({'url':original,'document_id':doc_id,'status':'original_read'})
                                break
                        except Exception:
                            # Untrusted upstream details are deliberately excluded.
                            entry['originals'].append({'url':result['url'],'status':'unavailable_or_irrelevant'})
            except Exception:
                entry['coverage']='public discovery unavailable; independent coverage incomplete'
            storage.event(run_id,'targeted_retrieval',entry)
    peer_ids=[]
    for peer_name in profile.peers[:2]:
        peer=resolve(peer_name)
        for hypothesis in hypotheses[:2]:
            rows=documents.search(peer.id,hypothesis.search_terms,2,cutoff)
            for row in rows:
                found[row['id']]=row
                peer_ids.append(row['id'])
    return list(found.values()),audit,peer_ids


def evidence_gate(analysis, review, passages, calculations, audit):
    lookup={p['id']:p for p in passages}
    cited={c.passage_id for c in analysis.discovery.citations}
    cited_rows=[lookup[i] for i in cited if i in lookup]
    # Company/peer disclosures each count as one origin, including mirrored PDFs.
    from backend.companies import profiles
    companies=list(profiles().values())
    origins={}
    for row in cited_rows:
        host=(urlsplit(row['original_url']).hostname or '').casefold()
        owner=next((p.id for p in companies if any(host==d or host.endswith('.'+d) for d in p.domains)),None)
        key='company:'+owner if owner else 'publisher:'+host.removeprefix('www.')
        # Local files retain their subject's origin; a filename is not an independent source.
        if not host:key='company:'+row.get('company','unknown')
        origins.setdefault(key,set()).add(row.get('sha256') or row['document_id'])
    hashes=set()
    distinct=0
    for values in origins.values():
        if values-hashes:distinct+=1
        hashes.update(values)
    linked=[c for c in calculations if c.get('inputs') and all(i.get('passage_id') in cited for i in c['inputs'])]
    reasons=[]
    if not analysis.sufficient:reasons.append('The analyst found insufficient evidence.')
    if review.verdict!='supported':reasons.append('The opposing-evidence review did not support the candidate.')
    if distinct<2:reasons.append('The discovery lacks two distinct cited evidence origins.')
    if not linked:reasons.append('No saved calculation is linked to the discovery citations.')
    if not analysis.timeline:reasons.append('A source-grounded timeline has not been established.')
    challenged=any(a['side']=='challenge' and (a['local_passages'] or any(o['status']=='original_read' for o in a['originals'])) for a in audit)
    if not challenged:reasons.append('No usable evidence was found for the targeted opposing search.')
    admitted=not reasons
    return {'admitted':admitted,'rating':'Moderate' if admitted else 'Weak',
            'reasons':reasons or ['Cited distinct origins, dated evidence, linked arithmetic and a supported opposing review. Source independence and causality still require human review.'],
            'candidate_origins':sorted(origins),'distinct_content_origins':distinct,
            'linked_calculations':linked,'independence_status':'Domain/registered-company grouping and identical-content deduplication; ownership and syndication not independently certified.'}


def latest_report(company, run_id=None):
    clause=' AND id=?' if run_id else ''
    for row in storage.rows("SELECT id,status,report_json FROM research_runs WHERE company=? AND report_json IS NOT NULL AND json_extract(report_json,'$.investigation_version') IN (2,3)"+clause+' ORDER BY created_at DESC LIMIT 1',(company,run_id) if run_id else (company,)):
        report=json.loads(row['report_json'])
        if report.get('investigation_version') in (2,3):
            return row['id'],report
    return None,None


def present(company, run_id=None):
    run_id,report=latest_report(company,run_id) if run_id else latest_report(company)
    if not report:return None
    lookup={p['id']:p for p in report.get('passages',[])}
    def statement(item):
        if not item:return None
        citations=[]
        for citation in item.get('citations',[]):
            p=lookup.get(citation['passage_id'])
            if p:
                citations.append({'title':p.get('title') or 'Source document','page':p['pdf_page'],'quote':citation['quote'],
                    'url':f'/documents/{p["document_id"]}/original','original_url':p['original_url']})
        return {'text':item['text'],'citations':citations}
    gate=report.get('discovery_checks',{})
    calculations=[]
    for c in gate.get('linked_calculations',[]):
        item={k:c[k] for k in ('id','formula','value','unit','periods') if k in c}
        item['citations']=statement({'text':'Calculation inputs','citations':[
            {'passage_id':i['passage_id'],'quote':i.get('source_quote') or lookup.get(i['passage_id'],{}).get('text','')[:1000]}
            for i in c.get('inputs',[]) if i.get('passage_id') in lookup]})['citations']
        calculations.append(item)
    return {'run_id':run_id,'checked_at':report.get('completed_at',report['created_at']),
            'status':'supported_candidate' if gate.get('admitted') else 'insufficient_evidence',
            'discovery':statement(report.get('discovery')),
            'candidate':statement(report.get('candidate_discovery')),
            'significance':[statement(s) for s in report.get('significance',[])],
            'timeline':[{'date':s['date'],**statement(s)} for s in report.get('timeline',[])],
            'counterargument':statement(report.get('counterargument')),
            'falsification_condition':report.get('falsification_condition'),
            'evidence_strength':report.get('evidence_strength'),
            'calculations':calculations,
            'financial_data_gaps':report.get('financial_data_gaps',[]),
            'limitations':gate.get('reasons',['The investigation did not establish a supported finding.'])+[
                'Distinct domains do not by themselves establish independent ownership or reporting. Novelty and causal claims require further verification.'],
            'report_url':f'/runs/{run_id}/report'}
