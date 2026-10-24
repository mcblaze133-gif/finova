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
from fastapi.responses import FileResponse,HTMLResponse
from pydantic import BaseModel,Field,ConfigDict
from backend import storage,research,excel_engine,evidence_packs,company_updates,results,model
from backend.companies import resolve

router=APIRouter()
TASKS=set()
ADMISSION=asyncio.Lock()

@router.get('/sector/coverage')
def sector_coverage():
    from backend import sector_status
    return sector_status.build()

@router.get('/sector/coverage/view',response_class=HTMLResponse)
def sector_coverage_view():
    from backend import sector_status
    from html import escape
    from datetime import datetime, timedelta, timezone
    def shown_date(value):
        try:return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone(timedelta(hours=5,minutes=30))).strftime('%d %b %Y, %H:%M IST')
        except (ValueError,AttributeError):return 'Not established'
    data=sector_status.build();rows=[]
    for c in data['companies']:
        links=' '.join(f'<a href="{escape(c[k],quote=True)}">{label}</a>' for k,label in
                       [('report_url','Findings'),('pdf_url','PDF'),('excel_url','Excel'),('verification_url','Sources & checks')] if c.get(k))
        status='Delivery checks passed' if c['checks_passed'] else 'Delivery checks incomplete'
        gaps=', '.join(c.get('unresolved_areas',[])) or 'No delivered assessment'
        active='<small>New investigation in progress. Links show the dated delivered report.</small>' if c.get('active_report_id') else ''
        rows.append('<tr><td><strong>'+escape(c['company'])+'</strong><small>'+escape(c['role'])+'</small>'+active+'</td><td>'+status+
                    '<small>'+str(c.get('operating_complete',0))+'/'+str(c.get('operating_total',0))+' operating areas completed</small><small>Report: '+escape(shown_date(c.get('prepared_at')))+'<br>News: '+escape(shown_date(c.get('news_checked_at')))+'</small></td><td>'+escape(gaps)+
                    '</td><td>'+str(c.get('operating_benchmark_rows',0))+' operating benchmarks<small>'+('Reviewed conditional peer cross-check' if c.get('peer_valuation_available') else 'Valuation comparison unavailable')+'</small></td><td>'+links+'</td></tr>')
    u=data['universe']
    return HTMLResponse('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Finova | Sector coverage</title><style>'
        'body{font:15px/1.6 Segoe UI,Arial,sans-serif;background:#f5f6f2;color:#163039;margin:0;padding:35px}main{max-width:1400px;margin:auto}a{color:#126b59;margin-right:12px}h1{font-size:34px}table{border-collapse:collapse;background:white;width:100%}th,td{text-align:left;vertical-align:top;padding:18px;border-bottom:1px solid #dce5e3}th{background:#122c35;color:white}small{display:block;color:#61757a;margin-top:8px}.scroll{overflow-x:auto}footer{margin-top:25px}</style></head><body><main>'
        '<a href="/">Finova research</a><h1>Company coverage</h1><p>Five populated companies, one shared research and valuation workflow. Results remain qualified where evidence is incomplete.</p>'
        '<div class="scroll"><table><thead><tr><th>Company</th><th>Delivery checks</th><th>Research gaps</th><th>Peer comparison</th><th>Reports & evidence</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><footer><p>'+escape(data['meaning'])+'</p><p>Universe reference: '+escape(u['reference_date'])+'. <a href="'+escape(u['source'],quote=True)+'">NSE constituent reference</a>. '+escape(u['limitation'])+'</p><p>Britannia is supplementary coverage. <a href="https://www.niftyindices.com/Press_Release/ind_prs21022025.pdf">NSE removal notice</a>.</p><small>Register checked '+escape(shown_date(data['checked_at']))+'</small></footer></main></body></html>')

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
    from backend import verification,source_reviews
    workbook_hash=evidence_packs.digest_file(Path(export[0]['workbook_path']))
    audit=verification.build(company,inputs,news,export[0]['workbook_path'],workbook_hash)
    comparison = inputs.get('sector_comparison')
    if comparison and 'Sector comparison' in data:
        # Public outputs read saved Excel results, never a parallel Python model.
        comparison = json.loads(json.dumps(comparison))
        cells = data['Sector comparison']
        for i, peer in enumerate(comparison['rows'], 6):
            peer['metrics'] = {key:cells.get(f'{column}{i}') for key,column in
                               [('revenue_growth','E'),('ebitda_margin','F'),('cash_conversion','G'),
                                ('capex_ratio','H'),('net_debt_sales','I')]}
    peers=inputs.get('peer_valuation')
    if peers and 'Peer valuation' in data:
        peers=json.loads(json.dumps(peers));cells=data['Peer valuation']
        for i,peer in enumerate(peers['companies'],21):
            peer['metrics']={key:cells.get(f'{column}{i}') for key,column in
                [('reported_pe','AD'),('adjusted_pe','AE'),('ev_ebitda','AF'),('ev_ebit','AG'),
                 ('ev_sales','AH'),('ps','AI'),('adjusted_ebitda_crore','AA'),('adjusted_pat_crore','AB')]}
        peers['ranges']={key:{'low':cells.get(f'D{r}'),'midpoint':cells.get(f'E{r}'),
            'high':cells.get(f'F{r}'),'usable_peers':cells.get(f'G{anchor}')} for key,r,anchor in
            [('pe',6,11),('ev_ebitda',7,12)]}
    return {'report_id':report_id,'company_id':company,'company':resolve(company).legal_name,'generated_at':storage.now(),
        'started_at':run[0]['created_at'],'preview':preview,'research':raw,'history':history,'forecasts':forecasts,
        'valuation':results.saved_valuation(company,export_id=export_id),'methods':inputs['methods'],
        'assumptions':inputs['assumptions'],'market_notes':inputs.get('market_notes',[]),'news':news,
        'verification_audit':audit,'workbook_sha256':workbook_hash,
        'workbook_url':f'http://127.0.0.1:8000/excel/exports/{export_id}',
        'native_excel_verified':False,'research_excel_linked':bool(linked),'inputs_created_at':inputs['created_at'],'validation_only':bool(raw.get('validation_only')),
        'sector_comparison':comparison,'peer_valuation':peers,'source_reviews':source_reviews.build(company)}

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
        targeted = None
        if not raw.get('validation_only'):
            from backend import sector_research
            from backend import research_gaps
            stage(report_id,'targeted_evidence')
            initial = excel_engine.company_package(company, include_comparison=False)
            review_payload = {'company_id':company,'company':resolve(company).legal_name,
                              'research':raw,'history':initial['historical_statements']}
            targeted = await research_gaps.investigate(review_payload, live=True)
            review_payload['targeted_research'] = targeted
            stage(report_id,'section_analysis')
            await sector_research.complete(review_payload,research_id)
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
            if targeted is not None:
                # Original sources must reach the section reviewer before the
                # workbook binds its research hash. Do not repeat web searches.
                targeted['signals'] = research_gaps.signals(payload.get('history', {}))
                payload['targeted_research'] = targeted
            else:
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
        'revision_note':payload.get('revision_note'),
        'verification':{'checked_at':payload['verification_audit']['checked_at'],'systems':payload['verification_audit']['systems']} if payload.get('verification_audit') else None,
        'verification_url':f'/analysis-reports/{report_id}/verification/view' if payload.get('verification_audit') else None,
        'view_url':f'/analysis-reports/{report_id}/view' if job['pdf_path'] else None,
        'pdf_url':f'/analysis-reports/{report_id}/pdf' if job['pdf_path'] else None,
        'excel_url':f'/excel/exports/{job["export_id"]}' if job['pdf_path'] and job['export_id'] else None}

@router.get('/analysis-reports/{report_id}/verification')
def report_verification(report_id:str):
    audit=json.loads(row(report_id)['snapshot_json'] or '{}').get('verification_audit')
    if not audit:raise HTTPException(404,'No verification register is attached to this saved report.')
    return audit


@router.get('/analysis-reports/{report_id}/findings')
def report_findings(report_id:str):
    from backend import discovery_view
    job=row(report_id)
    if job['status'] not in ('completed','partial') or not job['snapshot_json']:
        raise HTTPException(409,'Findings are not ready for this report.')
    payload=json.loads(job['snapshot_json'])
    if payload.get('company_id')!=job['company'] or payload.get('report_id')!=report_id:
        raise HTTPException(409,'Report identity does not match its findings.')
    return discovery_view.build(payload)


@router.get('/analysis-reports/{report_id}/verification/view')
def report_verification_view(report_id:str):
    from backend import verification
    payload=json.loads(row(report_id)['snapshot_json'] or '{}')
    audit=payload.get('verification_audit')
    if not audit:raise HTTPException(404,'No verification register is attached to this report.')
    return HTMLResponse(verification.render(audit,payload['company']))


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
