"""No-key syndicated news discovery. Headlines are leads, never verified events."""
import asyncio
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit
import httpx
from backend import storage


def queries(profile, baseline):
    name = profile.legal_name.replace(' Limited', '')
    # Infer candidate research topics from disclosed text, not universal FMCG assumptions.
    vocabulary=('wheat','palm oil','milk','sugar','coffee','cocoa','tea','tobacco','paper','wood pulp','soap noodles','packaging','freight','crude oil')
    mentions={term:len(re.findall(r'\b'+re.escape(term)+r'\b',baseline.casefold())) for term in vocabulary}
    # Mentions identify research topics, not expenditure weights or proven risk.
    terms=sorted((term for term in vocabulary if mentions[term]),key=lambda term:-mentions[term])
    result = [('company', f'"{name}" when:120d'),
              ('market_regulatory',f'"{name}" (board OR regulation OR tax OR acquisition OR dividend) when:90d')]
    if terms:
        result.append(('industry_commodities',f'India ({" OR ".join(terms[:4])}) (prices OR supply) when:30d'))
        result.append(('geopolitical',f'(conflict OR tariff OR sanctions OR shipping) ({" OR ".join(terms[:3])}) India when:30d'))
    else:
        result.extend([('industry_commodities', f'"{name}" (industry OR input costs OR supply) when:30d'),
                       ('geopolitical',f'"{name}" (conflict OR tariffs OR trade OR shipping) when:30d')])
    result.append(('macro','India (inflation OR repo rate OR rupee OR rural consumption) when:30d'))
    return result


def parse_feed(data, category, known=()):
    if len(data) > 1_000_000 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Unsupported or oversized news feed.')
    root = ET.fromstring(data)
    leads = []
    for item in root.findall('./channel/item')[:100]:
        title = ' '.join((item.findtext('title') or '').split())[:500]
        url = item.findtext('link') or ''
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != 'news.google.com' or not parsed.path.startswith('/rss/articles/'):
            continue
        try:
            published = parsedate_to_datetime(item.findtext('pubDate') or '')
            if published.tzinfo is None:
                continue
            if published.astimezone(timezone.utc) > datetime.fromisoformat(storage.now()):
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        if not title or (storage.today_ist()-published.date()).days > 125:
            continue
        key = hashlib.sha256((item.findtext('guid') or url).encode()).hexdigest()
        source = item.find('source')
        leads.append({'lead_id':key, 'headline':title, 'url':url, 'publisher':source.text if source is not None else 'Unknown',
                      'published_at':published.isoformat(), 'event_date':None, 'category':category,
                      'novelty':'previously_seen_feed_lead' if key in known else 'newly_discovered_lead_not_proven_new_event',
                      'verification':'syndicated headline only; original article and event date unverified',
                      'confidence':'unassessed'})
    return sorted(leads, key=lambda x:x['published_at'], reverse=True)


def conditional_impact(category):
    routes = {
        'company':(['volume_growth','capex_ratio','ebitda_margin'], 'Check the actual announcement before changing demand, investment or operating forecasts.'),
        'market_regulatory':(['tax_rate','price_mix_growth','selected_pe'], 'If a decision applies to the company, assess tax, pricing and comparable valuation effects; a market opinion is not a company decision.'),
        'industry_commodities':(['ebitda_margin','price_mix_growth','nwc_ratio'], 'If exposed input costs or supply terms change, margins, pricing recovery and working capital may change. Verify cost mix, inventory lags and hedges.'),
        'geopolitical':(['ebitda_margin','volume_growth','nwc_ratio'], 'If the company has the relevant sourcing, shipping or market exposure, costs, availability and demand may change. Exposure and magnitude are unverified.'),
        'macro':(['volume_growth','risk_free_rate','pretax_cost_debt'], 'If demand, currency or financing conditions affect the company, review volumes and capital costs. Do not infer a new WACC directly from a headline.')}
    drivers, mechanism = routes[category]
    return {'drivers_to_review':drivers, 'mechanism':mechanism, 'direction':'uncertain',
            'interpretation_status':'conditional research checklist, not an assessed company impact',
            'quantitative_treatment':'No numerical assumption change applied.'}


async def discover(profile, baseline, directory, known=()):
    async def one(category, query, client):
        url = 'https://news.google.com/rss/search?'+urlencode({'q':query,'hl':'en-IN','gl':'IN','ceid':'IN:en'})
        try:
            async with client.stream('GET', url) as response:
                if response.status_code != 200:
                    raise ValueError('News feed unavailable.')
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 1_000_000:
                        raise ValueError('News feed too large.')
            all_leads = parse_feed(bytes(data), category, known)
            if category in ('company', 'market_regulatory'):
                brand = profile.legal_name.split()[0].casefold()
                if brand == 'tata':
                    brand = 'tata consumer' if profile.id == 'tata-consumer' else profile.legal_name.removesuffix(' Limited').casefold()
                all_leads = [lead for lead in all_leads if any(re.search(r'\b'+re.escape(alias)+r'\b', lead['headline'].casefold())
                    for alias in (brand, profile.id.replace('-', ' ')))]
                all_leads = [lead for lead in all_leads if not re.search(r'share price today|price action view|technical analysis|stock price today', lead['headline'], re.I)]
            leads = all_leads[:3]
            (directory / f'news-{category}.xml').write_bytes(data)
            for lead in leads:
                lead.update(conditional_impact(category))
            return leads, {'category':category,'query':query,'status':'feed_read','leads':len(leads),
                           'response_sha256':hashlib.sha256(data).hexdigest()}
        except (httpx.HTTPError, ValueError, ET.ParseError):
            return [], {'category':category,'query':query,'status':'unavailable','leads':0}
    async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False,
                                 headers={'User-Agent':'SignalAIResearch/0.4'}) as client:
        responses = await asyncio.gather(*(one(c,q,client) for c,q in queries(profile,baseline)))
    unique = {}
    for leads, _ in responses:
        for lead in leads:
            unique.setdefault(lead['lead_id'], lead)
    return list(unique.values()), [coverage for _,coverage in responses]


async def primary_evidence(profile, directory):
    """Read registered investor pages and their newest result disclosures afresh.

    Archives preserve exactly what the assessment received. Company statements
    remain attributed claims, not independent confirmation of their contents.
    """
    import json
    from urllib.parse import urljoin
    from backend import documents
    fetcher = documents.Fetcher(profile.domains)
    sources, blocks, coverage, candidates = [], [], [], {}

    async def read(url, title, is_seed=False, original_news=False,regulatory=False):
        try:
            async with asyncio.timeout(35):
                source_fetcher = documents.Fetcher(['ccpa.doca.gov.in']) if regulatory else documents.Fetcher(['newsonair.gov.in']) if original_news else fetcher
                data, kind, final = await source_fetcher.fetch(url)
                from backend import public_sources
                reviewed=public_sources.reviewed_pages(data,final) if regulatory else None
                pages,links=(reviewed,[]) if reviewed else await asyncio.to_thread(documents.extract_cached,data,kind)
            digest = hashlib.sha256(data).hexdigest()
            (directory / ('official-'+digest+('.pdf' if data.startswith(b'%PDF') else '.html'))).write_bytes(data)
            sid = len(sources)
            sources.append({'source_id':sid,'url':final,'title':title[:400],
                'verification':('original regulator document retrieved; selected passages manually transcribed from page images and bound to this exact file hash; impact and subsequent appeal status not verified' if reviewed else 'original regulator document retrieved and text extracted; interpretation, impact and appeal status require review') if regulatory else 'original public-broadcaster news article retrieved; underlying regulatory notice not independently retrieved' if original_news else 'original company disclosure retrieved; company claim, not independent corroboration',
                'source_kind':'primary_regulatory_document' if regulatory else 'original_news_article' if original_news else 'primary_company_disclosure','sha256':digest,'retrieved_at':storage.now()})
            # Prefer the consolidated statements and management release in a
            # combined filing. Do not let lengthy HTML navigation consume context.
            ranked = sorted(enumerate(pages,1),key=lambda p:(
                not bool(re.search(r'consolidated|press release|highlights|quarter.*ended',p[1],re.I)),p[0]))
            budget = 15000 if not is_seed else 5000
            for page, text in ranked:
                text = '\n'.join(' '.join(line.split()) for line in text.splitlines()).strip()
                if len(text)<80 or budget<100:
                    continue
                excerpt = text[:min(6000,budget)]
                blocks.append({'text':f'Original {"regulator (reviewed visual transcription)" if regulatory and reviewed else "regulator" if regulatory else "public news" if original_news else "company"} source, page {page}. Retrieved {storage.now()}.\n'+excerpt,
                               'source_ids':[sid]})
                budget -= len(excerpt)
            receipt=next((r for r in reversed(source_fetcher.receipts) if r['url']==final),None)
            coverage.append({'url':final,'status':'original_read','sha256':digest,
                             'freshness_check':receipt})
            if is_seed:
                for href,label in links:
                    target=urljoin(final,href)
                    if '.pdf' not in target.casefold() or not re.search(r'result|quarter|earnings|financial',target+' '+label,re.I):
                        continue
                    try:
                        documents.allowed_url(target,profile.domains)
                    except ValueError:
                        continue
                    candidates[target]=label or 'Company financial disclosure'
        except (ValueError, OSError, TimeoutError, httpx.HTTPError):
            coverage.append({'url':url,'status':'unavailable','limitation':'Original source could not be read within retrieval policy and time limits.'})

    # Bounded source requests, no search API or paid model calls.
    for seed in profile.seeds[:2]:
        await read(seed,'Company investor updates',True)
    ordered=sorted(candidates.items(),key=lambda x:documents.rank_link(x),reverse=True)
    for url,title in ordered[:2]:
        await read(url,title)
    watchlist=storage.PROJECT_DIR/'config/public_source_watchlist.json'
    if watchlist.exists():
        for item in json.loads(watchlist.read_text(encoding='utf-8')).get(profile.id,[])[:2]:
            regulatory=item.get('kind')=='regulatory'
            try:
                documents.allowed_url(item['url'],['ccpa.doca.gov.in'] if regulatory else ['newsonair.gov.in'])
            except ValueError:
                continue
            await read(item['url'],item['title'],original_news=not regulatory,regulatory=regulatory)
    (directory/'official-source-coverage.json').write_text(json.dumps(coverage,indent=2),encoding='utf-8')
    return {'sources':sources,'blocks':blocks,'coverage':coverage}
