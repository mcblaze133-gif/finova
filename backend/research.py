import asyncio
import hashlib
import json
import uuid
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from backend import storage, documents, finance, valuation, tables
from backend.companies import resolve
from backend.facts import Fact, validate_fact, normalized
from backend.model import generate, ModelUnavailable


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class RunRequest(Strict):
    company: str = Field(min_length=2, max_length=160)
    refresh: bool = True
    max_documents: int = Field(default=4, ge=1, le=6)
    evidence_cutoff: date = Field(default_factory=storage.today_ist)
    evidence_pack_only: bool = False
    force_fresh: bool = False


class Hypothesis(Strict):
    question: str = Field(min_length=10, max_length=400)
    alternative: str = Field(min_length=10, max_length=400)
    search_terms: str = Field(min_length=3, max_length=200)


class Plan(Strict):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=2)


class Extracted(Strict):
    facts: list[Fact] = Field(max_length=24)


class Citation(Strict):
    passage_id: int = Field(gt=0)
    excerpt_id: int | None = Field(default=None, ge=0, le=20)
    quote: str = Field(default='', max_length=1200)


class Statement(Strict):
    text: str = Field(min_length=5, max_length=1500)
    citations: list[Citation] = Field(min_length=1, max_length=5)


class TimelineItem(Statement):
    date: date

class SectorSection(Strict):
    topic: Literal['Business and products','Demand, volume and pricing','Costs and profitability',
                   'Segments and geography','Competition and economic moat','Management and governance',
                   'Capital allocation','Risks and catalysts','Macro and commodity exposure']
    statements: list[Statement] = Field(min_length=1,max_length=3)
    investor_use: str = Field(min_length=15,max_length=700)


class Analysis(Strict):
    sufficient: bool
    discovery: Statement
    significance: list[Statement] = Field(min_length=3, max_length=5)
    timeline: list[TimelineItem] = Field(max_length=8)
    counterargument: Statement
    falsification_condition: str = Field(min_length=20, max_length=1000)
    limitations: list[str] = Field(max_length=12)
    sector_sections: list[SectorSection] = Field(default_factory=list,max_length=9)


class Review(Strict):
    verdict: Literal['supported', 'weakened', 'rejected']
    counterargument: Statement
    falsification_condition: str = Field(min_length=20, max_length=1000)
    reasons: list[str] = Field(min_length=1, max_length=10)
    unsupported_sector_topics: list[str] = Field(default_factory=list,max_length=9)


def create_run(request, *, db=None):
    profile = resolve(request.company)
    if request.evidence_cutoff > storage.today_ist():
        raise ValueError('Evidence cutoff cannot be in the future.')
    if db is None:
        with storage.database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            return create_run(request, db=connection)
    run_id = uuid.uuid4().hex
    active = db.execute("SELECT COUNT(*) FROM research_runs WHERE status IN ('queued','running')").fetchone()[0]
    if request.force_fresh and active:
        raise ValueError('A research task is already running. Wait for completion before starting a fresh investigation.')
    if active >= 2:
        raise ValueError('Two runs are already active. Wait for completion.')
    db.execute('INSERT INTO research_runs(id,company,created_at,updated_at,evidence_cutoff,status,stage,request_json) VALUES(?,?,?,?,?,?,?,?)',
               (run_id, profile.id, storage.now(), storage.now(), request.evidence_cutoff.isoformat(), 'queued', 'queued', request.model_dump_json()))
    return run_id


def safe_passages(rows, budget=30000, per_passage_limit=6500):
    result, used = [], 0
    for row in rows:
        # Preserve source offsets by passing a visible exact excerpt.
        text = '\n'.join(' '.join(line.split()) for line in row['text'].splitlines())[:per_passage_limit]
        if used + len(text) > budget:
            break
        result.append({'id': row['id'], 'document_id': row['document_id'], 'pdf_page': row['pdf_page'],
                       'text': text, 'publication_date': row.get('publication_date'),
                       'original_url': row['original_url'], 'title':row.get('title','Source document'),
                       'sha256':row.get('sha256'), 'company':row.get('company'),
                       'period_sort_hint_unverified':row.get('period_sort_hint_unverified'),
                       'document_kind':row.get('document_kind')})
        used += len(text)
    return result


def check_statement(statement, passages):
    lookup = {p['id']: p for p in passages}
    for citation in statement.citations:
        row = lookup.get(citation.passage_id)
        if row and citation.excerpt_id is not None:
            start = citation.excerpt_id * 700
            exact = row['text'][start:start + 700]
            if not exact.strip():
                raise ValueError('Generated excerpt identifier is outside its source passage.')
            citation.quote = exact
        if not row or normalized(citation.quote) not in normalized(row['text']):
            raise ValueError('Generated citation is missing or does not match its source passage.')
        if len(citation.quote.strip()) < 10:
            raise ValueError('Generated citation has no usable source text.')
    if isinstance(statement, TimelineItem):
        # The date must be present in the exact quoted evidence.
        from backend.facts import quote_dates
        if not any(statement.date in quote_dates(c.quote) for c in statement.citations):
            raise ValueError('Timeline date is not grounded in cited source text.')


def check_statements(analysis, passages):
    statements = [analysis.discovery, *analysis.significance, *analysis.timeline, analysis.counterargument] if isinstance(analysis, Analysis) else [analysis.counterargument]
    if isinstance(analysis, Analysis):
        statements += [s for section in analysis.sector_sections for s in section.statements]
    for statement in statements:
        check_statement(statement, passages)


def isolate_analysis(analysis, passages):
    """Reject individual unsupported timeline/sector items, retaining other work."""
    rejected=[]; timeline=[]; sections=[]
    for item in analysis.timeline:
        try:check_statement(item, passages);timeline.append(item)
        except ValueError as exc:rejected.append('Timeline item rejected: '+str(exc))
    analysis.timeline=timeline
    for section in analysis.sector_sections:
        valid=[]
        for statement in section.statements:
            try:check_statement(statement, passages);valid.append(statement)
            except ValueError as exc:rejected.append(section.topic+': '+str(exc))
        if valid:
            section.statements=valid;sections.append(section)
    analysis.sector_sections=sections
    return rejected


def excerpt_context(passages):
    return [{k: v for k, v in p.items() if k != 'text'} | {
        'excerpts': [{'excerpt_id': i // 700, 'text': p['text'][i:i + 700]} for i in range(0, len(p['text']), 700)]}
        for p in passages]


def fact_context(valid,calculations):
    required={i for c in calculations for i in c['input_fact_ids']}
    selected=[f for f in valid if f['id'] in required]
    selected += [f for f in valid if f['id'] not in required][:max(0,24-len(selected))]
    # Exact source text is already in the excerpt catalog and audit records.
    # Avoid sending each long table quotation a second time.
    return [{k:v for k,v in f.items() if k!='source_quote'} for f in selected]


def calculation_context(calculations):
    return [{k:v for k,v in c.items() if k in ('id','formula','value','unit','input_fact_ids','periods','warnings')}
            | {'input_passage_ids':[f['passage_id'] for f in c['inputs']]} for c in calculations]


def online_context(context):
    # Full news findings remain in the report. Only a bounded, explicitly
    # qualified summary is needed for historical hypothesis testing.
    result={k:context.get(k) for k in ('status','checked_at','treatment')}
    result['events']=[{k:v[:350] if isinstance(v,str) else v for k,v in event.items()}
                      for event in context.get('events',[])[:2]]
    result['news_leads']=[{k:v[:250] if isinstance(v,str) else v for k,v in event.items()}
                          for event in context.get('news_leads',[])[:2]]
    result['limitations']=[s[:250] for s in context.get('limitations',[])[:2]]
    return result


def base_report(run, profile):
    return {'run_id': run['id'], 'company': profile.legal_name, 'business_model': profile.business_model,
            'created_at': run['created_at'], 'evidence_cutoff': run['evidence_cutoff'],
            'status': 'partial', 'discovery': None, 'significance': [], 'timeline': [],
            'calculations': [], 'counterargument': None, 'falsification_condition': None,
            'evidence_strength': {'rating': 'Weak', 'reasons': ['No completed grounded discovery yet.']},
            'limitations': ['Core financial retrieval uses seeded official archives. Separate online update coverage is bounded and may be incomplete.',
                            'Company-origin documents are not independent sources, even when mirrored elsewhere.',
                            'Financial grounding is conservative; ambiguous table facts are quarantined.',
                            'Human evaluation against 30 critical facts has not been completed.'],
            'sources': [], 'passages': [], 'valuation': valuation.method_register(),
            'novelty': 'Unverified. No claim of novelty.', 'peer_comparison': 'Not completed.',
            'formula_version': finance.VERSION, 'prompt_version': 'v1',
            'investment_recommendation': 'None; research context only.'}


def finish(run_id, report):
    report['completed_at'] = storage.now()
    with storage.database() as db:
        calls = db.execute('SELECT model_calls FROM research_runs WHERE id=?', (run_id,)).fetchone()[0]
        report['model_calls'] = calls
        report['remaining_provider_quota'] = 'not exposed; check provider console'
        db.execute('UPDATE research_runs SET status=?,stage=?,report_json=?,updated_at=? WHERE id=?',
                   (report['status'], 'finished', json.dumps(report, ensure_ascii=False), storage.now(), run_id))
    path = storage.PROJECT_DIR / 'reports' / (run_id + '.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def available_calculations(company, allowed_ids, run_id):
    valid = storage.rows("SELECT f.* FROM facts f JOIN passages p ON p.id=f.passage_id JOIN documents d ON d.id=p.document_id WHERE d.company=? AND f.validation_status='validated' ORDER BY f.period_end DESC", (company,))
    valid = [f for f in valid if f['passage_id'] in allowed_ids]
    # Conflicting source values for the same metric/basis/period require
    # reconciliation. A lexically grounded fact is not automatically a
    # comparable financial input (for example after a restatement).
    groups={}
    for fact in valid:
        key=tuple(fact[k] for k in ('metric','period_start','period_end','unit','currency','accounting_scope','operations_scope'))+(fact['definition'].casefold(),)
        groups.setdefault(key,[]).append(fact)
    eligible=[]
    for group in groups.values():
        values={finance.decimal(f['value_decimal']) for f in group}
        if len(values)==1:eligible.append(group[0])
        else:
            for fact in group:
                fact['calculation_input_eligible']=False
                fact['comparability_note']='Conflicting source values for this period and definition; reconcile restatements or scope before calculation.'
    calculations = []
    for formula, metrics in (('revenue_growth', ('revenue', 'revenue')), ('profit_growth', ('profit', 'profit')),
                             ('total_income_growth', ('total_income', 'total_income')), ('cash_conversion', ('operating_cash_flow', 'profit')),
                             ('ebit_margin', ('ebit', 'revenue')), ('ebitda_margin', ('ebitda', 'revenue'))):
        pairs=[]
        for a in [f for f in eligible if f['metric']==metrics[0]]:
            candidates=sorted([f for f in eligible if f['metric']==metrics[1]],key=lambda f:(f['passage_id']!=a['passage_id'],f['period_end']),reverse=False)
            for b in candidates:
                try:
                    if a['id']==b['id']:continue
                    growth=metrics[0]==metrics[1]
                    if growth and (not a['period_start'] or int(a['period_end'][:4])-int(b['period_end'][:4])!=1 or a['period_start']<=b['period_end']):continue
                    finance.comparable([dict(a,company=company),dict(b,company=company)],across_periods=growth)
                    if finance.decimal(b['value_decimal'])<=0:continue
                    if formula=='cash_conversion' and finance.decimal(b['value_decimal'])<finance.decimal('0.000001'):continue
                    pairs.append((a,b));break
                except ValueError:continue
        pairs.sort(key=lambda pair:pair[0]['period_end'],reverse=True)
        # Preserve a current and an older comparison rather than selecting
        # only the newest possible pair. Keep role inputs bounded.
        chosen=pairs[:1]+(pairs[-1:] if len(pairs)>1 else [])
        for a,b in chosen:
            existing=storage.rows('SELECT id,output_json FROM calculations WHERE run_id=? AND formula=? AND input_fact_ids=?',
                                 (run_id,formula,json.dumps([a['id'],b['id']])))
            calculation=json.loads(existing[0]['output_json']) if existing else finance.calculate(formula,[a['id'],b['id']],run_id)
            if existing:calculation['id']=existing[0]['id']
            calculation['periods']=[{'start':f['period_start'],'end':f['period_end'],'accounting_scope':f['accounting_scope'],'operations_scope':f['operations_scope']} for f in (a,b)]
            calculations.append(calculation)
    return valid, calculations


async def execute(run_id):
    run = storage.rows('SELECT * FROM research_runs WHERE id=?', (run_id,))[0]
    request = RunRequest.model_validate_json(run['request_json'])
    profile = resolve(run['company'])
    report = base_report(run, profile)
    report['investigation_version']=3 if request.force_fresh else 2
    with storage.database() as db:
        db.execute("UPDATE research_runs SET status='running' WHERE id=?", (run_id,))
    try:
        async with asyncio.timeout(600):
            from backend import company_updates, evidence_packs
            prepared=None
            update_id=None
            if request.evidence_pack_only:
                await asyncio.to_thread(evidence_packs.refresh,profile.id)
                from backend import investigation
                prepared,report['evidence_pack_read']=await asyncio.to_thread(investigation.prepared_passages,profile.id)
                if request.force_fresh:
                    selected=investigation.search_prepared(prepared,'revenue profit cash inventory receivables volume margin consolidated guidance outlook',12)
                    report['evidence_pack_read']['physical_pdf_review']=await asyncio.to_thread(investigation.read_selected_pdf_pages,profile.id,selected)
            if request.refresh and request.evidence_cutoff == storage.today_ist() and (request.force_fresh or evidence_packs.read_manifest(profile.id)):
                update_id, created = company_updates.create(profile.id,force_new=True) if request.force_fresh else company_updates.create(profile.id)
                report['update_run_id']=update_id
                if created:
                    try:
                        await asyncio.wait_for(company_updates.execute(update_id),120)
                    except TimeoutError:
                        report['limitations'].append('The preliminary news check timed out. Targeted investigation continues with qualified coverage.')
            report['external_updates'] = company_updates.context(profile.id, request.evidence_cutoff,run_id=update_id) if request.force_fresh and update_id else company_updates.context(profile.id, request.evidence_cutoff) if not request.force_fresh else {'status':'not_checked','limitations':['The fresh online check did not complete. No earlier news assessment was substituted.']}
            report['limitations'].extend(report['external_updates'].get('limitations', []))
            if request.force_fresh and report['external_updates'].get('provider_status') in (401,403,429):
                raise ModelUnavailable('The fresh check stopped after a Gemini quota or authentication refusal. No further model calls or earlier findings were substituted.')
            if request.force_fresh and report['external_updates'].get('provider_status') in (500,502,503,504):
                raise ModelUnavailable('The current assessment is unavailable because the model service failed. No further model calls were made; no earlier findings were substituted.')
            storage.event(run_id, 'discovery', {'refresh': request.refresh, 'coverage': 'official archives'})
            if request.refresh and not request.evidence_pack_only:
                result = await documents.discover(profile, request.max_documents,
                                                   lambda detail: storage.event(run_id, 'retrieval', detail))
                report['retrieval'] = result
                if result['errors']:
                    report['limitations'].append('Some source retrievals failed; see retrieval log.')
            all_sources = storage.rows('SELECT id,title,original_url,publication_date,retrieved_at,sha256 FROM documents WHERE company=?', (profile.id,))
            report['sources'] = all_sources
            # Unknown publication dates may aid current exploration, but never enter a
            # historical-cutoff analysis. Missing dates are visible in the report.
            historical = request.evidence_cutoff < storage.today_ist()
            cutoff = request.evidence_cutoff.isoformat() if historical else None
            from backend import investigation
            rows = investigation.search_prepared(prepared,'revenue profit cash inventory receivables volume margin consolidated guidance outlook',12) if prepared is not None else documents.search(profile.id, 'revenue profit cash inventory receivables volume stores margin consolidated', 10, cutoff)
            passages = safe_passages(rows,per_passage_limit=2200) if prepared is not None else safe_passages(rows)
            report['passages'] = passages
            if any(not p['publication_date'] for p in all_sources):
                report['limitations'].append('Some publication dates are unknown. These documents are excluded from historical-cutoff runs; current-run chronology remains unverified.')
            if not passages:
                raise ValueError('Insufficient readable financial evidence. No model was called.')
            plan = await generate(run_id, 'planner', {'company': profile.model_dump(), 'passages': passages if prepared is not None else passages[:4],
                'history_policy':'Compare older and newer supplied evidence, including guidance versus delivery. Period sort hints are unverified and are not event dates or financial period facts.'}, Plan)
            report['hypotheses'] = plan.model_dump()['hypotheses']
            from backend import investigation
            targeted,audit,peer_ids = await investigation.collect(profile,plan.hypotheses,cutoff,request.refresh and not historical,run_id,prepared=prepared) if prepared is not None else await investigation.collect(profile,plan.hypotheses,cutoff,request.refresh and not historical,run_id)
            report['research_plan_execution']=audit
            seen={p['id'] for p in targeted}
            candidates=targeted+[p for p in rows if p['id'] not in seen]
            if prepared is not None:
                # Rebalance the collected set before applying the input budget;
                # otherwise the first supporting query crowds out later years
                # and the opposing evidence. Peers/public originals are retained.
                subject=[p for p in candidates if p.get('company') in (None,profile.id)]
                other=[p for p in candidates if p.get('company') not in (None,profile.id)]
                required={a['local_passages'][0] for a in audit if a.get('local_passages')}
                chosen=[p for p in subject if p['id'] in required]
                chosen_ids={p['id'] for p in chosen}
                chosen += [p for p in investigation.balance_prepared(subject,12) if p['id'] not in chosen_ids]
                candidates=chosen+other[:4]
                passages=safe_passages(candidates,35000,per_passage_limit=min(3500,35000//max(1,len(candidates))))
                report['historical_evidence_selection']={
                    'policy':'Period-diverse question-directed excerpts; supporting and opposing queries are retained. This is not an exhaustive reading or a verified financial history.',
                    'passage_ids':[p['id'] for p in passages],
                    'period_hints_unverified':sorted({tuple(p['period_sort_hint_unverified']) for p in passages if p.get('period_sort_hint_unverified')}),
                    'publication_dates_known':sum(bool(p.get('publication_date')) for p in passages)}
            else:passages=safe_passages(candidates,35000)
            report['passages']=passages
            report['sources']=storage.rows('SELECT id,title,original_url,publication_date,retrieved_at,sha256 FROM documents WHERE company=?',(profile.id,))
            storage.event(run_id, 'planner', {'passages': len(passages)})
            deterministic_facts = tables.extract_company(profile.id, [p['id'] for p in passages])
            report['table_parser_facts_added'] = deterministic_facts
            if deterministic_facts:
                report['limitations'].append('Comparative table periods use a calendar-quarter convention; inspect table proofs and restatements before release.')
            _, report['calculations'] = available_calculations(profile.id, {p['id'] for p in passages}, run_id)
            subject_passages=[p for p in passages if p.get('company') in (None,profile.id)]
            cache_key = hashlib.sha256(json.dumps({'version': 'extractor-v2-subject-only','company':profile.id, 'passages': subject_passages}, sort_keys=True).encode()).hexdigest()
            cached = [] if request.force_fresh else storage.rows('SELECT result_json FROM extraction_cache WHERE cache_key=?', (cache_key,))
            if cached:
                extracted = Extracted.model_validate_json(cached[0]['result_json'])
                storage.event(run_id, 'extraction', {'cache': True})
            else:
                extracted = await generate(run_id, 'extractor', {'passages': subject_passages}, Extracted)
                with storage.database() as db:
                    db.execute('INSERT OR IGNORE INTO extraction_cache VALUES(?,?,?)', (cache_key, extracted.model_dump_json(), storage.now()))
            allowed_ids = {p['id'] for p in subject_passages}
            results = []
            for fact in extracted.facts:
                if fact.passage_id not in allowed_ids:
                    raise ValueError('Extractor referenced a passage it was not given.')
                results.append(validate_fact(fact, profile.id))
            report['fact_checks'] = results
            valid, calculations = available_calculations(profile.id, allowed_ids, run_id)
            report['calculations'] = calculations
            report['financial_data_gaps']=sorted({
                f"{f['metric'].replace('_',' ')} for {f['period_end']} ({f['accounting_scope']}, {f['operations_scope']}): selected sources report conflicting values. Reconcile restatements or reporting scope before using this period in calculations."
                for f in valid if f.get('calculation_input_eligible') is False})
            peer_context=[p for p in passages if p['id'] in peer_ids]
            report['peer_comparison']={'status':'question-directed candidate evidence; accounting comparability is not assumed','passage_ids':peer_ids}
            storage.event(run_id,'counterevidence',{'queries':[a['query'] for a in audit if a['side']=='challenge'],
                          'coverage':'Targeted local search and bounded public-original retrieval; failures remain visible.'})
            analysis = await generate(run_id, 'analyst', {'company': profile.model_dump(), 'plan': plan.model_dump(),
                                      'passages': excerpt_context(passages), 'validated_facts': fact_context(valid,calculations),
                                      'calculations': calculation_context(calculations),
                                      'online_update_review': online_context(report['external_updates'])}, Analysis)
            report["limitations"].extend(isolate_analysis(analysis, passages))
            report["sector_sections"] = [s.model_dump(mode="json") for s in analysis.sector_sections]
            check_statements(analysis, passages)
            candidate = analysis.model_dump(mode='json')
            novelty={'status':'not checked for historical/cached investigation','leads':[]}
            if request.refresh and not historical:
                try:
                    async with asyncio.timeout(20):
                        novelty={'status':'search leads require originality review; novelty not established',
                                 'leads':await investigation.public_search(analysis.discovery.text[:220],profile.legal_name)}
                except Exception:
                    novelty={'status':'public novelty search unavailable; no novelty claim','leads':[]}
            report['novelty_review']=novelty
            # Source text already exists in the catalog; do not duplicate it in
            # the critic's candidate record and consume scarce model context.
            def strip_quotes(value):
                if isinstance(value, dict):
                    return {k: strip_quotes(v) for k, v in value.items() if k != 'quote'}
                if isinstance(value, list):
                    return [strip_quotes(v) for v in value]
                return value
            review_context = {'candidate': strip_quotes(candidate), 'passages': excerpt_context(passages),
                              'novelty_search':novelty,
                              'online_update_review': online_context(report['external_updates']),
                              'peer_context': [{'passage_id':p['id'],'company':p.get('company')} for p in peer_context], 'search_coverage': report['limitations'][:2],
                              'calculations': calculation_context(calculations),
                              'validated_facts': fact_context(valid,calculations)}
            review = await generate(run_id, 'reviewer', review_context, Review)
            check_statements(review, passages + peer_context)
            pipeline_limitations = report['limitations'][:]
            report.update(analysis.model_dump(mode='json'))
            rejected_topics=set(review.unsupported_sector_topics)
            report['sector_sections']=[s for s in report['sector_sections'] if s['topic'] not in rejected_topics]
            report['excluded_sector_topics']=sorted(rejected_topics)
            report['review'] = review.model_dump(mode='json')
            report['counterargument'] = review.counterargument.model_dump()
            report['falsification_condition'] = review.falsification_condition
            report['limitations'] = list(dict.fromkeys([*pipeline_limitations, *report['limitations'],
                                                        'Independent novelty and counterevidence web search are incomplete.']))
            gate=investigation.evidence_gate(analysis,review,passages,calculations,audit)
            report['discovery_checks']=gate
            report['status'] = 'completed' if gate['admitted'] else 'partial'
            report['evidence_strength'] = {'rating':gate['rating'],'reasons':gate['reasons']}
            if not gate['admitted']:
                report['candidate_discovery'] = report.pop('discovery')
                report['discovery'] = None
                report['limitations'].append('Candidate lacks a supported review or a reproducible financial calculation; no confirmed discovery is presented.')
            with storage.database() as db:
                db.execute('INSERT INTO claims(run_id,statement,verdict,evidence_json) VALUES(?,?,?,?)',
                           (run_id, analysis.discovery.text, review.verdict, analysis.discovery.model_dump_json()))
    except (ModelUnavailable, ValueError) as exc:
        report['limitations'].append(str(exc))
        storage.event(run_id, 'partial', {'reason': str(exc)})
    except TimeoutError:
        report['limitations'].append('600-second investigation budget reached. Unfinished research is not claimed complete.')
    except asyncio.CancelledError:
        report['limitations'].append('Service shutdown interrupted the run.')
        finish(run_id, report)
        raise
    except Exception:
        report['status'] = 'failed'
        report['limitations'].append('Unexpected processing error. No raw upstream error or credentials are exposed.')
        storage.event(run_id, 'error', {'reason': 'Processing failed.'})
    finish(run_id, report)
