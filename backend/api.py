import asyncio
import hashlib
import json
import re
from datetime import date
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, ConfigDict
from backend import storage, documents, finance, research, valuation
from backend.companies import Company, profiles, resolve
from backend.facts import Fact, validate_fact

router = APIRouter()
TASKS = set()


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Ingest(Strict):
    company: str = Field(min_length=2, max_length=160)
    url: str = Field(max_length=2048)
    title: str = Field(default='Public disclosure', max_length=300)
    publication_date: date | None = None


class Calculation(Strict):
    formula: Literal['revenue_growth', 'profit_growth', 'total_income_growth', 'cash_conversion', 'ebit_margin', 'ebitda_margin']
    fact_ids: list[int] = Field(min_length=2, max_length=2)


class ScenarioRequest(Strict):
    scenarios: list[valuation.Scenario] = Field(min_length=1, max_length=3)
    target_enterprise_value: str | None = None


class MultipleRequest(Strict):
    values: dict[str, str] = Field(max_length=20)
    observation_date: date
    currency: Literal['INR']
    accounting_scope: Literal['consolidated', 'standalone']
    source_url: str = Field(pattern=r'^https://', max_length=2048)
    lease_policy: str = Field(min_length=10, max_length=600)
    rationale: str = Field(min_length=20, max_length=1000)


def run_row(run_id):
    if not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise HTTPException(404, 'Run not found.')
    result = storage.rows('SELECT * FROM research_runs WHERE id=?', (run_id,))
    if not result:
        raise HTTPException(404, 'Run not found.')
    return result[0]


@router.get('/', response_class=HTMLResponse)
def home():
    return (storage.PROJECT_DIR / 'backend' / 'results.html').read_text(encoding='utf-8')


@router.get('/companies')
def companies():
    return [p.model_dump() for p in profiles().values()]


@router.post('/companies', status_code=201)
def register_company(profile: Company):
    for domain in profile.domains:
        if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}', domain):
            raise HTTPException(422, 'Invalid public source domain.')
    for seed in profile.seeds:
        try:
            documents.allowed_url(seed, profile.domains)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    if profile.id in profiles():
        raise HTTPException(409, 'Company already registered; source profiles are immutable through the API.')
    with storage.database() as db:
        db.execute('INSERT INTO companies VALUES(?,?,?,?)', (profile.id, profile.legal_name, profile.business_model, profile.model_dump_json()))
    return profile


@router.post('/documents', status_code=201)
async def ingest_document(request: Ingest):
    try:
        profile = resolve(request.company)
        document_id = await asyncio.wait_for(documents.ingest(profile, request.url, request.title,
                                           request.publication_date.isoformat() if request.publication_date else None), 100)
        return {'document_id': document_id}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(502, 'Source access or extraction failed; no upstream details exposed.') from None


@router.get('/documents')
def list_documents(company: str):
    try:
        profile = resolve(company)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    return storage.rows('SELECT id,company,title,original_url,publication_date,retrieved_at,sha256 FROM documents WHERE company=?', (profile.id,))


@router.get('/documents/{document_id}/original')
def original(document_id: int):
    found = storage.rows('SELECT local_path,sha256 FROM documents WHERE id=?', (document_id,))
    if not found:
        raise HTTPException(404, 'Document not found.')
    path = (storage.PROJECT_DIR / found[0]['local_path']).resolve()
    if not path.is_relative_to((storage.DATA_DIR / 'raw').resolve()) or not path.is_file():
        raise HTTPException(404, 'Original unavailable.')
    with path.open('rb') as source:
        is_pdf=source.read(5)==b'%PDF-'
        source.seek(0)
        digest=hashlib.file_digest(source,'sha256').hexdigest()
    if digest!=found[0]['sha256']:
        raise HTTPException(409,'Archived source integrity check failed. The cited original was not served.')
    # PDF citations open at #page; untrusted HTML remains an attachment.
    return FileResponse(path, filename=path.name,
                        media_type='application/pdf' if is_pdf else 'application/octet-stream',
                        content_disposition_type='inline' if is_pdf else 'attachment',
                        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.get('/passages/{passage_id}')
def passage(passage_id: int):
    result = storage.rows('SELECT p.*,d.original_url,d.title,d.publication_date FROM passages p JOIN documents d ON d.id=p.document_id WHERE p.id=?', (passage_id,))
    if not result:
        raise HTTPException(404, 'Passage not found.')
    return result[0]


@router.get('/search')
def search(company: str, query: str = Query(min_length=3, max_length=300), limit: int = Query(default=8, ge=1, le=15)):
    try:
        return documents.search(resolve(company).id, query, limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/facts/validate')
def fact_validate(fact: Fact):
    try:
        return validate_fact(fact)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/facts')
def list_facts(company: str):
    try:
        return storage.rows('SELECT f.* FROM facts f JOIN passages p ON p.id=f.passage_id JOIN documents d ON d.id=p.document_id WHERE d.company=?', (resolve(company).id,))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/facts/{fact_id}')
def fact_details(fact_id: int):
    result = storage.rows('SELECT f.*,c.checks_json,c.version,p.pdf_page,d.original_url,d.title FROM facts f JOIN fact_checks c ON c.fact_id=f.id JOIN passages p ON p.id=f.passage_id JOIN documents d ON d.id=p.document_id WHERE f.id=?', (fact_id,))
    if not result:
        raise HTTPException(404, 'Fact not found.')
    return result[0]


@router.post('/calculate')
def calculation(request: Calculation):
    try:
        return finance.calculate(request.formula, request.fact_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/runs', status_code=202)
async def start_run(request: research.RunRequest):
    try:
        run_id = research.create_run(request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    task = asyncio.create_task(research.execute(run_id))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return {'run_id': run_id, 'status_url': f'/runs/{run_id}', 'report_url': f'/runs/{run_id}/report'}


class FreshInvestigation(Strict):
    company: str = Field(min_length=2,max_length=160)


@router.post('/investigations',status_code=202)
async def fresh_investigation(request: FreshInvestigation):
    from backend import evidence_packs, model
    try:
        profile=resolve(request.company)
        if not evidence_packs.read_manifest(profile.id):
            raise HTTPException(409,'Prepare this company’s compact evidence pack before investigating.')
        model.model_settings()
        model.require_capacity(5)
        run_id=research.create_run(research.RunRequest(company=profile.id,refresh=True,evidence_pack_only=True,force_fresh=True))
    except model.ModelUnavailable as exc:
        raise HTTPException(429,str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(503,str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None
    task=asyncio.create_task(research.execute(run_id))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return {'run_id':run_id,'status_url':f'/runs/{run_id}','report_url':f'/investigations/{run_id}/report','mode':'fresh_investigation'}


@router.get('/investigations/{run_id}/report')
def fresh_investigation_report(run_id: str):
    row=run_row(run_id)
    if not json.loads(row['request_json']).get('force_fresh'):
        raise HTTPException(404,'Fresh investigation not found.')
    if row['status'] in ('queued','running') or not row['report_json']:
        raise HTTPException(409,'The fresh investigation is still running. No previous report is substituted.')
    from backend.results import company_results
    return company_results(row['company'],fresh_run_id=run_id)


@router.get('/runs')
def list_runs():
    return storage.rows('SELECT id,company,created_at,updated_at,status,stage,model_calls FROM research_runs ORDER BY created_at DESC LIMIT 30')


@router.get('/runs/{run_id}')
def run_status(run_id: str):
    row = run_row(run_id)
    row.pop('report_json')
    row['events'] = storage.rows('SELECT created_at,stage,detail_json FROM run_events WHERE run_id=? ORDER BY id', (run_id,))
    return row


@router.get('/runs/{run_id}/report')
def run_report(run_id: str):
    row = run_row(run_id)
    if not row['report_json']:
        raise HTTPException(409, 'Report is still being built.')
    return json.loads(row['report_json'])


@router.get('/valuation/methods')
def methods():
    return valuation.method_register()


@router.post('/valuation/scenarios')
def scenario_valuation(request: ScenarioRequest):
    if len({s.name for s in request.scenarios}) != len(request.scenarios):
        raise HTTPException(422, 'Scenario names must be unique.')
    try:
        results = []
        for scenario in request.scenarios:
            result = valuation.dcf(scenario)
            result['sensitivity'] = valuation.sensitivity(scenario)
            if request.target_enterprise_value is not None:
                result['reverse_dcf'] = valuation.reverse_dcf(scenario, request.target_enterprise_value)
            results.append(result)
        valuation_id = __import__('uuid').uuid4().hex
        with storage.database() as db:
            db.execute('INSERT INTO valuation_runs VALUES(?,?,?,?,?)', (valuation_id, None, request.model_dump_json(), json.dumps(results), storage.now()))
            for result in results:
                db.execute('INSERT INTO valuation_outputs(valuation_id,method,status,output_json) VALUES(?,?,?,?)',
                           (valuation_id, 'FCFF DCF', 'scenario only', json.dumps(result)))
            for scenario in request.scenarios:
                for parameter, value in scenario.model_dump().items():
                    db.execute('INSERT INTO valuation_assumptions(valuation_id,scenario,parameter,value_json,rationale) VALUES(?,?,?,?,?)',
                               (valuation_id, scenario.name, parameter, json.dumps(value), scenario.rationale))
        return {'valuation_id': valuation_id, 'results': results}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/valuation/multiples')
def multiple_valuation(request: MultipleRequest):
    if request.observation_date > storage.today_ist():
        raise HTTPException(422, 'Market observation date is in the future.')
    try:
        result = valuation.multiples(request.values)
        result['snapshot'] = request.model_dump(mode='json')
        result['stale'] = (storage.today_ist() - request.observation_date).days > 7
        result['input_validation'] = 'Scenario inputs supplied by caller; source URL is recorded, not verified.'
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/evaluation')
def evaluation_status():
    return {'release_ready': False, 'status': 'Engineering tests do not replace financial source review.',
            'required': ['30 manually checked facts across three business models', 'Independent counterevidence/novelty search',
                         'Live free-tier structured output benchmark', 'Held-out and uncached company runs',
                         'n8n workflow import and restore rehearsal'],
            'cases': storage.rows('SELECT * FROM evaluation_cases ORDER BY id')}
