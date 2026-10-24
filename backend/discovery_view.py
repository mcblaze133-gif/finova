"""Public finding cards from one frozen report, with conservative attribution.

No model calls, latest-report fallback or promotion of a hypothesis to a fact.
Source links are attached before a claim is admitted to the website.
"""
import re
import unicodedata
from urllib.parse import urlsplit


def safe_url(value):
    if not isinstance(value, str):
        return None
    if re.fullmatch(r'/documents/[1-9][0-9]*/original#page=[1-9][0-9]*', value):
        return value
    try:
        p = urlsplit(value)
        if p.scheme == 'https' and p.hostname and not p.username and not p.password and p.port in (None,443):
            return value
    except ValueError:
        pass
    return None


def normal(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def build(payload):
    raw = payload.get('research') or {}
    lookup = {p['id']:p for p in raw.get('passages', [])}
    omitted = 0

    def cited(item):
        if not item or not item.get('text') or not item.get('citations'):
            return None
        sources = []
        for citation in item['citations']:
            p = lookup.get(citation.get('passage_id'))
            quote = citation.get('quote')
            if not p or not quote or normal(quote) not in normal(p.get('text')):
                return None
            document, page = p.get('document_id'), p.get('pdf_page')
            if type(document) is not int or type(page) is not int or min(document,page) < 1:
                return None
            sources.append({'title':p.get('title') or 'Archived source', 'page':page,
                'url':f'/documents/{document}/original#page={page}',
                'publisher_url':safe_url(p.get('original_url')), 'quote':quote,
                'source_company':p.get('company'), 'date':p.get('publication_date')})
        return {'text':item['text'], 'sources':list({s['url']:s for s in sources}.values())}

    cards = []
    gate = raw.get('discovery_checks') or {}
    thesis = raw.get('discovery') if gate.get('admitted') else raw.get('candidate_discovery') or raw.get('discovery')
    claim = cited(thesis)
    if claim:
        counter = cited(raw.get('counterargument'))
        cards.append({'kind':'hypothesis', 'title':'Research thesis', 'text':claim['text'],
            'verified':False,
            'verification_label':'Corroboration checks passed; independent review pending' if gate.get('admitted') else 'Hypothesis · not verified',
            'verification_detail':'The cited excerpts match archived source text. This does not establish independent confirmation of the conclusion.',
            'sources':claim['sources'],
            'investor_use':'Test this interpretation against the counterargument and subsequent disclosures before changing investment assumptions.',
            'counterargument':counter['text'] if counter else 'A source-supported counterargument has not been established.',
            'counter_sources':counter['sources'] if counter else [],
            'falsification':raw.get('falsification_condition'), 'comparison':[]})
    elif thesis:
        omitted += 1

    history = payload.get('history') or {}
    # Re-derive the question selection from this report's saved diagnostics.
    # Arbitrary prose in a stored signal cannot masquerade as a checked metric.
    from backend.research_gaps import signals
    for signal in signals(history):
        refs = []
        keys={k for point in signal['comparison'] for k in point if k!='period'}
        metrics=set()
        if 'revenue_growth' in keys:metrics.add('revenue')
        if 'ebitda_margin' in keys:metrics.update(('ebitda','revenue'))
        if 'cash_conversion' in keys:metrics.update(('cfo','net_income'))
        if 'cash_after_capex_crore' in keys:metrics.update(('cfo','capex'))
        # Comparing two growth rates needs three revenue observations. Include
        # the earliest denominator's disclosure rather than only the latest PDF.
        periods=history.get('periods', [])[-(3 if 'revenue_growth' in keys else 2):]
        for period in periods:
            for metric in sorted(metrics):
                for ref in period.get('sources', {}).get(metric, []):
                    url = safe_url(ref.get('url'))
                    if url:
                        refs.append({'title':ref.get('file','Financial statement').replace('\\','/').split('/')[-1],
                                     'url':url,'page':ref.get('pages'),'date':period.get('end')})
        refs = list({r['url']:r for r in refs}.values())
        if not refs:
            omitted += 1
            continue
        cards.append({'kind':'observation', 'title':signal['title'],'text':signal['observation'],
            'verified':False,'verification_label':'Financial observation · cause not verified',
            'verification_detail':'Uses the report’s saved Excel diagnostics and linked historical inputs. Numerical reproducibility is separate from verification of the proposed cause.',
            'sources':refs, 'investor_use':signal['investor_use'],
            'counterargument':signal['alternative'],'counter_sources':[],
            'falsification':signal['falsification'],'comparison':signal['comparison']})

    # These are disclosed business interpretations, not non-obvious discoveries.
    preferred = ['Demand, volume and pricing','Costs and profitability','Capital allocation',
                 'Risks and catalysts','Segments and geography','Competition and economic moat']
    sections = raw.get('sector_sections') or []
    business = []
    for topic in preferred:
        section = next((s for s in sections if s.get('topic') == topic), None)
        if not section:
            continue
        for statement in section.get('statements', [])[:1]:
            claim = cited(statement)
            if not claim:
                omitted += 1
                continue
            counter = cited(section.get('counterevidence'))
            business.append({'kind':'disclosure','title':topic,'text':claim['text'],
                'verified':False,'verification_label':'Source-cited analysis · not independently verified',
                'verification_detail':'Cited excerpts match archived pages. Reported company statements and analyst interpretation are not independent confirmation.',
                'sources':claim['sources'], 'investor_use':section.get('investor_use'),
                'counterargument':counter['text'] if counter else None,
                'counter_sources':counter['sources'] if counter else [],
                'falsification':None, 'comparison':[], 'qualifications':section.get('gaps', [])})

    news = payload.get('news') or {}
    result = news.get('result') or {}
    source_lookup = {s['source_id']:s for s in result.get('sources', []) if 'source_id' in s}
    updates = []
    for event in result.get('events', [])[:4]:
        refs = [{'title':source_lookup[i].get('title','Update source'),'url':safe_url(source_lookup[i].get('url'))}
                for i in event.get('source_ids', []) if i in source_lookup]
        refs = [s for s in refs if s['url']]
        if not refs:
            omitted += 1
            continue
        updates.append({'kind':'update','title':event.get('headline') or event.get('title','Company development'),
            'text':event.get('potential_impact') or event.get('mechanism') or event.get('summary') or 'Read the underlying announcement before interpreting its financial impact.',
            'verified':False,'verification_label':'Update · independent verification incomplete',
            'verification_detail':event.get('fact_status') or 'Source retrieval and independent verification are distinct.',
            'sources':refs,'investor_use':event.get('review_action') or 'Check company exposure before changing forecasts.',
            'comparison':[], 'counterargument':None,'falsification':event.get('falsification')})

    val = payload.get('valuation') or {}
    return {'report_id':payload.get('report_id'),'company_id':payload.get('company_id'),
        'company':payload.get('company'),'generated_at':payload.get('generated_at'),
        'news_checked_at':news.get('checked_at'),'valuation_date':val.get('valuation_date'),
        'market_price_date':val.get('market_price_date'),'market_price':val.get('market_price'),
        'cards':cards,'business':business,'updates':updates,
        'verified_discoveries':0, 'omitted_unlinked_claims':omitted,
        'coverage':payload.get('coverage',{}),
        'qualification':'Verification labels describe the checks available. No finding in this report has a completed independent analyst verification attestation.'}
