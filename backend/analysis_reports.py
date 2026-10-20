"""One fresh evidence/news/research/Excel/PDF transaction per website request."""
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field,ConfigDict
from backend import storage,research,excel_engine,evidence_packs,company_updates,results,model
from backend.companies import resolve

router=APIRouter()
TASKS=set()
ADMISSION=asyncio.Lock()
class Request(BaseModel):
    model_config=ConfigDict(extra='forbid')
    company:str=Field(min_length=2,max_length=160)

def row(report_id):
    if not re.fullmatch(r'[a-f0-9]{32}',report_id):raise HTTPException(404,'Report not found.')
    rows=storage.rows('SELECT * FROM analysis_reports WHERE id=?',(report_id,))
    if not rows:raise HTTPException(404,'Report not found.')
    return rows[0]

def stage(report_id,name,**fields):
    with storage.database() as db:
        db.execute('UPDATE analysis_reports SET stage=?,updated_at=?'+''.join(f',{k}=?' for k in fields)+' WHERE id=?',
                   (name,storage.now(),*fields.values(),report_id))

def workbook_values(path):
    ns=results.NS
    with ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist())>60_000_000:raise ValueError('Workbook exceeds report read limit.')
        strings=[''.join(si.itertext()) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',ns)]
        rels={r.get('Id'):r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        sheets={}
        for s in ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',ns):
            target=rels[s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
            target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            values={}
            for c in ET.fromstring(z.read(target)).findall('.//s:sheetData/s:row/s:c',ns):
                value=c.findtext('s:v',namespaces=ns)
                if c.get('t')=='e':raise ValueError('Workbook contains a saved formula error.')
                if c.get('t')=='s':value=strings[int(value)]
                elif c.get('t')=='inlineStr':value=''.join(c.find('s:is',ns).itertext())
                elif value is not None:
                    try:value=float(value)
                    except ValueError:pass
                values[c.get('r')]=value
            sheets[s.get('name')]=values
        return sheets

def snapshot(company,research_id,export_id,report_id,*,preview=False):
    run=storage.rows('SELECT * FROM research_runs WHERE id=? AND company=?',(research_id,company))
    export=storage.rows("SELECT * FROM excel_exports WHERE id=? AND company=? AND status='exported'",(export_id,company))
    if not run or not run[0]['report_json'] or not export:raise ValueError('This run has no matching research and workbook.')
    raw=json.loads(run[0]['report_json']);inputs=json.loads(export[0]['input_json'])
    data=workbook_values(export[0]['workbook_path'])
    linked=inputs.get('research_report')
    if linked and (linked['report_id']!=report_id or linked['research_run_id']!=research_id):
        raise ValueError('The workbook belongs to a different research report.')
    if linked and linked.get('research_sha256')!=hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest():
        raise ValueError('Research findings changed after the workbook was prepared.')
    history=inputs.get('historical_statements',{})
    history['excel_diagnostics']=[]
    for i,p in enumerate(history.get('periods',[])):
        c=chr(68+i);s=data.get('Statement history',{})
        history['excel_diagnostics'].append({'end':p['end'],'net_margin':s.get(c+'29'),'cash_conversion':s.get(c+'30'),
            'cash_after_capex_crore':s.get(c+'31'),'revenue_growth':s.get(c+'32'),'ebitda_margin':s.get(c+'33')})
    forecasts={}
    for name in ('Bear','Base','Bull'):
        s=data[name]
        forecasts[name]=dict(periods=[results._date(s.get(c+'5')) for c in 'EFGHI'],
            rows={label:[s.get(c+str(r)) for c in 'EFGHI'] for r,label in [(8,'Revenue'),(10,'EBITDA'),(18,'FCFF'),(24,'Parent profit'),(28,'EPS')]},
            wacc=s.get('E36'),cost_equity=s.get('E35'),terminal_growth=s.get('E46'),
            ebitda_margin=[s.get(c+'95') for c in 'EFGHI'],
            dcf_bridge={label:s.get(cell) for label,cell in [('Enterprise value','E66'),('Equity value','F66'),('PV of terminal value','E54'),('Enterprise-to-equity adjustment','E61'),('Estimated interim FCFE','E84'),('Assumed interim distributions','E85')]},
            sensitivity={'wacc':[s.get(c+'8') for c in 'LMNOP'],'growth':[s.get('K'+str(r)) for r in range(9,14)],
                         'values':[[s.get(c+str(r)) for c in 'LMNOP'] for r in range(9,14)]},
            market_implied={'P/E':s.get('N19'),'EV/EBITDA':s.get('N20'),'EPS at selected P/E':s.get('N21')},
            terminal_dependence=data['Dashboard'].get('E32') if name=='Base' else None)
    news=company_updates.get(company,raw['update_run_id']) if raw.get('update_run_id') else None
    return {'report_id':report_id,'company_id':company,'company':resolve(company).legal_name,'generated_at':storage.now(),
        'started_at':run[0]['created_at'],'preview':preview,'research':raw,'history':history,'forecasts':forecasts,
        'valuation':results.saved_valuation(company,export_id=export_id),'methods':inputs['methods'],
        'assumptions':inputs['assumptions'],'market_notes':inputs.get('market_notes',[]),'news':news,
        'workbook_sha256':evidence_packs.digest_file(Path(export[0]['workbook_path'])),
        'workbook_url':f'http://127.0.0.1:8000/excel/exports/{export_id}',
        'native_excel_verified':False,'research_excel_linked':bool(linked),'inputs_created_at':inputs['created_at'],'validation_only':bool(raw.get('validation_only'))}

async def make_pdf(folder,payload):
    source=folder/'research-report-inputs.json';source.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    runtime=json.loads((storage.PROJECT_DIR/'config/runtime.json').read_text())
    python=runtime.get('pdf_python',sys.executable)
    target=folder/'Finova_Company_Research.pdf'
    p=await asyncio.create_subprocess_exec(python,str(storage.PROJECT_DIR/'tools/build_research_report.py'),
        '--input',str(source),'--out',str(target),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:out,err=await asyncio.wait_for(p.communicate(),120)
    except BaseException:
        if p.returncode is None:p.kill();await p.wait()
        raise
    (folder/'pdf-build.log').write_bytes(out+err)
    if p.returncode or not target.is_file():raise ValueError('The research PDF could not be prepared.')
    return target

async def execute(report_id):
    job=row(report_id);company=job['company'];folder=storage.PROJECT_DIR/'outputs'/report_id
    folder.mkdir(parents=True,exist_ok=False)
    try:
        stage(report_id,'research',status='running')
        research_id=job['research_run_id']
        await research.execute(research_id)
        completed=storage.rows('SELECT report_json,status FROM research_runs WHERE id=?',(research_id,))[0]
        raw=json.loads(completed['report_json'] or '{}')
        # Failed capacity/provider checks cannot become a fresh final report.
        # A partial, newly attempted review may still produce an explicitly
        # qualified report with current local financials and new calculations.
        read=raw.get('evidence_pack_read')
        if not read or not read.get('physical_pdf_review'):raise ValueError('The PDF review did not complete. No earlier report was substituted.')
        manifest=evidence_packs.read_manifest(company)
        if manifest['signature']!=read['signature'] or evidence_packs.source_fingerprints(company)!=manifest['source_fingerprints']:
            raise ValueError('Company documents changed during this run. Run the report again.')
        update_id=raw.get('update_run_id')
        update=company_updates.get(company,update_id) if update_id else None
        if not update:raise ValueError('The new online check was not recorded. No earlier news was substituted.')
        if not raw.get('validation_only'):
            from backend import sector_research
            stage(report_id,'section_analysis')
            await sector_research.complete({'company_id':company,'company':resolve(company).legal_name,'research':raw},research_id)
        stage(report_id,'valuation')
        export_id=uuid4().hex;stage(report_id,'valuation',export_id=export_id)
        built=await excel_engine.export_company(company,export_id,refresh_research=False,force_rebuild=True,research_update_id=update_id,analysis_report_id=report_id)
        if built['status']!='exported' or built.get('cached'):raise ValueError('A new workbook was not produced for this run.')
        if evidence_packs.source_fingerprints(company)!=manifest['source_fingerprints']:
            raise ValueError('Company documents changed during valuation. Run the report again.')
        payload=await asyncio.to_thread(snapshot,company,research_id,export_id,report_id)
        if not payload['valuation']:raise ValueError('The new workbook has no usable valuation results.')
        # Independent of Gemini availability: pursue numeric anomalies, contrary
        # explanations and peer-input gaps without manufacturing conclusions.
        from backend import research_gaps
        stage(report_id,'targeted_evidence')
        if payload.get('company_id'):
            payload['targeted_research']=await research_gaps.investigate(payload,live=True)
            payload['coverage']=research_gaps.report_coverage(payload)
        if evidence_packs.source_fingerprints(company)!=manifest['source_fingerprints']:
            raise ValueError('Company documents changed during targeted review. Run the report again.')
        stage(report_id,'report')
        path=await make_pdf(folder,payload)
        complete=completed['status']=='completed' and update['status']=='assessed' and payload.get('coverage',{}).get('complete',False)
        stage(report_id,'finished',status='completed' if complete else 'partial',pdf_path=str(path),snapshot_json=json.dumps(payload))
    except asyncio.CancelledError:
        stage(report_id,'interrupted',status='interrupted',error='Report preparation was interrupted. No previous report was substituted.')
        raise
    except ValueError as exc:
        stage(report_id,'failed',status='failed',error=str(exc))
    except Exception:
        stage(report_id,'failed',status='failed',error='The report could not be completed. No previous report was substituted.')

@router.post('/analysis-reports',status_code=202)
async def start(request:Request):
    async with ADMISSION:
        try:
            profile=resolve(request.company)
            if TASKS or storage.rows("SELECT id FROM analysis_reports WHERE status IN ('queued','running')"):
                raise HTTPException(409,'A report is being prepared. Wait for it to finish.')
            from backend.excel_api import EXPORT_JOBS
            if EXPORT_JOBS:raise HTTPException(409,'An Excel model is being prepared. Wait for it to finish.')
            readiness=await asyncio.to_thread(excel_engine.valuation_readiness,profile.id)
            if not readiness['can_build']:raise HTTPException(409,'Company financial inputs or valuation assumptions need review before this report can be built.')
            model.model_settings();model.require_capacity(10)
            research_id=research.create_run(research.RunRequest(company=profile.id,refresh=True,evidence_pack_only=True,force_fresh=True))
            report_id=uuid4().hex
            with storage.database() as db:
                db.execute('INSERT INTO analysis_reports(id,company,created_at,updated_at,status,stage,research_run_id) VALUES(?,?,?,?,?,?,?)',
                           (report_id,profile.id,storage.now(),storage.now(),'queued','queued',research_id))
        except model.ModelUnavailable as exc:raise HTTPException(429,str(exc)) from None
        except (ValueError,RuntimeError) as exc:raise HTTPException(409,str(exc)) from None
        task=asyncio.create_task(execute(report_id));TASKS.add(task);task.add_done_callback(TASKS.discard)
        return {'report_id':report_id,'status_url':f'/analysis-reports/{report_id}'}

@router.get('/analysis-reports/{report_id}')
def status(report_id:str):
    job=row(report_id)
    payload=json.loads(job['snapshot_json'] or '{}')
    areas=payload.get('coverage',{}).get('areas',[])
    overview={'valuation':payload.get('valuation',{}).get('weighted'),
        'research_areas':sum(a['area'] not in ('Financial statements','Conditional valuation','Current developments','Corroborated discovery') for a in areas),
        'completed_areas':sum(a.get('status')=='complete' and a['area'] not in ('Financial statements','Conditional valuation','Current developments','Corroborated discovery') for a in areas),
        'news_checked_at':(payload.get('news') or {}).get('checked_at')}
    return {k:job[k] for k in ('id','company','status','created_at','updated_at','error')}|{
        'validation_only':bool(payload.get('validation_only')),'overview':overview,'research_excel_linked':bool(payload.get('research_excel_linked')),
        'view_url':f'/analysis-reports/{report_id}/view' if job['pdf_path'] else None,
        'pdf_url':f'/analysis-reports/{report_id}/pdf' if job['pdf_path'] else None,
        'excel_url':f'/excel/exports/{job["export_id"]}' if job['pdf_path'] and job['export_id'] else None}

@router.get('/analysis-reports/{report_id}/pdf')
def pdf(report_id:str,view:bool=False):
    job=row(report_id)
    if job['status'] not in ('completed','partial') or not job['pdf_path']:raise HTTPException(409,'This report is not ready. No previous PDF is substituted.')
    path=Path(job['pdf_path']).resolve()
    if not path.is_relative_to((storage.PROJECT_DIR/'outputs'/report_id).resolve()) or not path.is_file():raise HTTPException(404,'Report unavailable.')
    return FileResponse(path,media_type='application/pdf',filename=f'Finova_{job["company"]}_Research.pdf',content_disposition_type='inline' if view else 'attachment',headers={'Cache-Control':'no-store'})


@router.get('/analysis-reports/{report_id}/view')
async def view_report(report_id:str):
    from backend import report_reader
    return await report_reader.view(report_id)

@router.get('/analysis-reports/{report_id}/pages/{page}')
async def view_report_page(report_id:str,page:int):
    from backend import report_reader
    return await report_reader.page_image(report_id,page)
