import asyncio
import re
from uuid import uuid4
from datetime import date
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from backend import storage, library, assumptions, excel_engine
from backend.valuation_spec import Assumption, DRIVERS
from backend import evidence_packs, company_updates

router = APIRouter()
JOBS = set()
EXPORT_JOBS = set()
EXPORT_ADMISSION = asyncio.Lock()


@router.get('/company-library')
def company_document_library():
    from backend.results import company_library
    return company_library()


@router.get('/results/{company}')
def financial_results(company: str):
    from backend.results import company_results
    try:
        return company_results(company)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

@router.get('/financial-history/{company}')
def historical_statements(company: str):
    from backend.companies import resolve
    from backend import financial_history
    from backend.results import saved_valuation
    try:
        profile=resolve(company)
        history=financial_history.build(profile.id)
        valuation=saved_valuation(profile.id)
        return {'history':history,'workbook':{'url':valuation['download_url'],'created_at':valuation['created_at']} if valuation else None}
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class CSVImport(Strict):
    relative_path: str = Field(min_length=1, max_length=500)

class PDFImport(CSVImport):
    company: str = Field(pattern=r'^[a-z0-9-]{2,60}$')
    original_url: str | None = Field(default=None, pattern=r'^https://', max_length=2048)
    source_date: date | None = None

class CompanyRequest(Strict):
    company: str = Field(pattern=r'^[a-z0-9-]{2,60}$')

class ChangePreview(CompanyRequest):
    instruction: str = Field(min_length=5, max_length=400)


@router.get('/evidence/{company}')
def evidence_status(company: str):
    try:
        manifest = evidence_packs.read_manifest(company)
        if manifest:
            result = {k: v for k, v in manifest.items() if k not in ('artifact_hashes', 'source_fingerprints')}
            result['refresh_required'] = evidence_packs.source_fingerprints(company) != manifest['source_fingerprints']
            return result
        return {'company': company, 'status': 'not prepared'}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/evidence/refresh', status_code=202)
async def evidence_refresh(request: CompanyRequest):
    try:
        refresh_id, created = company_updates.create(request.company)
        if created:
            task = asyncio.create_task(company_updates.execute(refresh_id))
            JOBS.add(task)
            task.add_done_callback(JOBS.discard)
        return {'refresh_id':refresh_id, 'status_url':f'/evidence/refreshes/{refresh_id}', 'status':'queued' if created else 'running'}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/evidence/refreshes/{refresh_id}')
def evidence_refresh_status(refresh_id: str):
    if not re.fullmatch(r'[a-f0-9]{32}', refresh_id):
        raise HTTPException(404, 'Refresh not found.')
    rows = storage.rows('SELECT * FROM company_update_runs WHERE id=?', (refresh_id,))
    if not rows:
        raise HTTPException(404, 'Refresh not found.')
    import json
    row = rows[0]
    return {'id':row['id'], 'company':row['company'], 'status':row['status'], 'stage':row['stage'],
            'checked_at':row['updated_at'], 'error':row['error'],
            'result':json.loads(row['result_json']) if row['result_json'] else None}


@router.get('/updates/{company}')
def company_update_status(company: str):
    try:
        evidence_packs.pack_root(company)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return company_updates.latest(company) or {'status':'not_checked','result':None}


@router.get('/evidence/{company}/search')
def evidence_search(company: str, q: str, full: bool = False):
    try:
        return evidence_packs.search(company, q, full=full)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/evidence/{company}/pdf')
def evidence_pdf(company: str):
    try:
        manifest = evidence_packs.read_manifest(company)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not manifest:
        raise HTTPException(404, 'Prepare the company evidence pack first.')
    if evidence_packs.source_fingerprints(company) != manifest['source_fingerprints']:
        raise HTTPException(409, 'Source files changed. Refresh the evidence pack before opening the current view.')
    root = evidence_packs.pack_root(company).resolve()
    path = (root / manifest['pdf']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, 'Evidence pack unavailable.')
    if evidence_packs.digest_file(path) != manifest['artifact_hashes'].get(manifest['pdf']):
        raise HTTPException(409, 'Company documents need to be refreshed.')
    return FileResponse(path, filename=f'{company}-valuation-evidence.pdf', media_type='application/pdf')


@router.get('/evidence/{company}/download/{kind}')
def evidence_download(company: str, kind: str):
    import csv
    import io
    import json
    if kind not in ('index','text'):
        raise HTTPException(404, 'Document download not found.')
    try:
        root = evidence_packs.pack_root(company).resolve()
        manifest = evidence_packs.read_manifest(company)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not manifest:
        raise HTTPException(404, 'Company documents are not prepared.')
    if evidence_packs.source_fingerprints(company) != manifest['source_fingerprints']:
        raise HTTPException(409, 'Company documents have changed. Refresh before downloading.')
    path = (root / manifest['pages']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, 'Company documents unavailable.')
    if evidence_packs.digest_file(path) != manifest['artifact_hashes'].get(manifest['pages']):
        raise HTTPException(409, 'Company documents need to be refreshed.')
    pages = json.loads(path.read_text(encoding='utf-8'))
    if kind == 'index':
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['Evidence PDF page','Original file','Original PDF page','Topics'])
        writer.writerows([p['pack_page'],p['source_file'],p['original_page'],'; '.join(p['reasons'])] for p in pages)
        data, suffix, media = '\ufeff'+output.getvalue(), 'csv', 'text/csv'
    else:
        data = 'Company document excerpts. Financial figures require validation against original pages.\n\n' + '\n\n'.join(
            f'Evidence PDF page {p["pack_page"]} | {p["source_file"]} | Original page {p["original_page"]}\n{p["text"]}' for p in pages)
        suffix, media = 'txt', 'text/plain'
    return Response(data, media_type=media, headers={'Content-Disposition':f'attachment; filename="{company}-company-evidence.{suffix}"'})

class AssumptionReplacement(Strict):
    assumption: Assumption
    reason: str = Field(min_length=5, max_length=1000)

@router.put('/assumptions')
def replace_assumption(request: AssumptionReplacement):
    return assumptions.save(request.assumption, reason=request.reason, replace_override=True)

@router.get('/library')
def inventory():
    return library.inventory()

@router.post('/library/csv')
def csv_import(request: CSVImport):
    try:
        return library.import_csv(request.relative_path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

@router.post('/library/pdf')
async def pdf_import(request: PDFImport):
    try:
        return await asyncio.to_thread(library.import_pdf, request.company, request.relative_path,
                                       request.original_url, request.source_date.isoformat() if request.source_date else None)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(422, 'PDF extraction failed; no financial inputs accepted.') from None

@router.get('/drivers/{company}')
def drivers(company: str):
    return {'observed': library.observed_drivers(company), 'definitions': DRIVERS,
            'note': 'Observed driver text does not establish a numerical forecast.'}

@router.get('/assumptions/{company}')
def list_assumptions(company: str):
    return assumptions.list_for(company)

@router.post('/assumptions')
def write_assumption(request: Assumption):
    try:
        return assumptions.save(request)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None

@router.post('/assumptions/preview')
def preview(request: ChangePreview):
    try:
        return assumptions.preview_change(request.company, request.instruction)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

@router.post('/excel/exports', status_code=202)
async def export(request: CompanyRequest):
    # Readiness yields to a worker thread. Serialize admission across that yield
    # so two simultaneous clicks cannot both pass the single-build guard.
    async with EXPORT_ADMISSION:
        return await _start_export(request)


async def _start_export(request):
    from backend.analysis_reports import TASKS as REPORT_TASKS
    if REPORT_TASKS:
        raise HTTPException(409,'A research report and Excel valuation are being prepared together. Wait for completion.')
    if EXPORT_JOBS:
        raise HTTPException(409, 'An Excel export is already being built.')
    readiness = await asyncio.to_thread(excel_engine.valuation_readiness, request.company)
    if not readiness['can_build']:
        raise HTTPException(409, {'message':'This company valuation has not been prepared yet.', 'missing':readiness['missing']})
    export_id = uuid4().hex
    with storage.database() as db:
        db.execute('INSERT INTO excel_exports(id,company,created_at,status,input_json) VALUES(?,?,?,?,?)',
                   (export_id, request.company, storage.now(), 'queued', '{}'))
    async def build():
        try:
            await excel_engine.export_company(request.company, export_id)
        except asyncio.CancelledError:
            with storage.database() as db:
                db.execute("UPDATE excel_exports SET status='interrupted',error='Workbook preparation cancelled during shutdown.' WHERE id=? AND status IN ('queued','building')", (export_id,))
            raise
        except Exception:
            with storage.database() as db:
                db.execute("UPDATE excel_exports SET status='failed',error='Workbook preparation failed.' WHERE id=?", (export_id,))
    task = asyncio.create_task(build())
    JOBS.add(task)
    EXPORT_JOBS.add(task)
    task.add_done_callback(JOBS.discard)
    task.add_done_callback(EXPORT_JOBS.discard)
    return {'export_id': export_id, 'status_url': f'/excel/exports/{export_id}/status', 'download_url': f'/excel/exports/{export_id}'}

def export_row(export_id):
    if not re.fullmatch(r'[a-f0-9]{32}', export_id):
        raise HTTPException(404, 'Export not found.')
    rows = storage.rows('SELECT * FROM excel_exports WHERE id=?', (export_id,))
    if not rows:
        raise HTTPException(404, 'Export not found.')
    return rows[0]

@router.get('/excel/exports/{export_id}/status')
def export_status(export_id: str):
    row = export_row(export_id)
    return {k: row[k] for k in ('id','company','status','error','created_at')}

@router.get('/excel/exports/{export_id}')
def download(export_id: str):
    row = export_row(export_id)
    if row['status'] != 'exported':
        raise HTTPException(409, 'Workbook is not ready.')
    path = __import__('pathlib').Path(row['workbook_path']).resolve()
    if not path.is_relative_to((storage.PROJECT_DIR/'outputs').resolve()) or not path.is_file():
        raise HTTPException(404, 'Workbook file unavailable.')
    return FileResponse(path, filename='Finova_FMCG_Valuation.xlsx', media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
