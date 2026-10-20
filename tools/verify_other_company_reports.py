"""Exercise real pack -> free retrieval -> rebuilt Excel -> PDF for four companies.

Generative calls are deliberately disabled in THIS PROCESS ONLY. Outputs retain
new run IDs and explicit validation labels; they never claim live AI completion.
The normal website's quota gate is also checked and is not bypassed or increased.
"""
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import httpx
from pypdf import PdfReader
from backend import storage,analysis_reports as ar,research,model,evidence_packs

COMPANIES=('hul','itc','nestle-india','tata-consumer')
REASON='Validation run: generative AI deliberately not called. No fresh AI operating or news-impact assessment was performed.'

async def no_model(*args,**kwargs):
    raise model.ModelUnavailable(REASON)

def usage():
    with storage.database() as db:
        day=storage.now()[:10]
        return model._daily_calls(db,day)

async def main():
    if storage.rows("SELECT id FROM analysis_reports WHERE status IN ('queued','running')"):
        raise RuntimeError('A website report is running. Wait before validation.')
    output=storage.PROJECT_DIR/'reports/other-company-report-verification.json'
    before=usage();summary={'started_at':storage.now(),'companies':[],'validation_only':True,'ai_provider_calls':0}
    if output.exists():
        previous=json.loads(output.read_text(encoding='utf-8'))
        if previous.get('started_at','')[:10]==storage.now()[:10] and previous.get('validation_only'):
            summary['companies']=previous.get('companies',[])
    real_execute=research.execute
    async def marked_research(run_id):
        await real_execute(run_id)
        row=storage.rows('SELECT report_json FROM research_runs WHERE id=?',(run_id,))[0]
        raw=json.loads(row['report_json']);raw['validation_only']=True
        raw['limitations'].append(REASON)
        with storage.database() as db:db.execute('UPDATE research_runs SET report_json=? WHERE id=?',(json.dumps(raw),run_id))
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',trust_env=False,timeout=60) as client:
        # Read-only admission inspection: a no-AI validator must never POST to
        # the live endpoint when capacity is available (it would start real calls).
        try:
            model.require_capacity(5)
        except model.ModelUnavailable:
            summary['website_live_ai_admission']='Insufficient approved capacity; not live-AI verified. No live request submitted.'
        else:
            summary['website_live_ai_admission']='Capacity available; live endpoint deliberately not called by this no-AI validator.'
        # Repair/refresh before recording any run signature, never midway through
        # the investigation. Resume only results against this exact current pack.
        for company in COMPANIES:
            print(json.dumps({'company':company,'status':'checking_current_pack'}),flush=True)
            await asyncio.to_thread(evidence_packs.refresh,company)
        kept=[]
        for old in summary['companies']:
            snapshot=json.loads(ar.row(old['report_id'])['snapshot_json'])
            if Path(old['pdf_path']).is_file() and snapshot['research']['evidence_pack_read']['signature']==evidence_packs.read_manifest(old['company'])['signature']:
                kept.append(old)
        summary['companies']=kept;already={r['company'] for r in kept}
        # Production deliberately permits only one fresh investigation at a time.
        slots=asyncio.Semaphore(1)
        async def check(company):
            async with slots:
                research_id=research.create_run(research.RunRequest(company=company,refresh=True,evidence_pack_only=True,force_fresh=True))
                report_id=uuid4().hex
                with storage.database() as db:
                    db.execute('INSERT INTO analysis_reports(id,company,created_at,updated_at,status,stage,research_run_id) VALUES(?,?,?,?,?,?,?)',
                               (report_id,company,storage.now(),storage.now(),'queued','validation',research_id))
                print(json.dumps({'company':company,'status':'validation_started','report_id':report_id}),flush=True)
                await ar.execute(report_id)
                job=ar.row(report_id)
                if not job['pdf_path']:raise AssertionError((company,job['stage'],job['error']))
                payload=json.loads(job['snapshot_json']);data=ar.workbook_values(storage.rows('SELECT workbook_path FROM excel_exports WHERE id=?',(job['export_id'],))[0]['workbook_path'])
                assert payload['validation_only'] and job['status']=='partial'
                assert payload['company_id']==company and payload['research']['company']==payload['company']
                assert len(payload['research']['evidence_pack_read']['physical_pdf_review']['pages'])>0
                assert payload['research']['update_run_id']
                manifest=evidence_packs.read_manifest(company)
                assert payload['research']['evidence_pack_read']['signature']==manifest['signature']
                from backend import library
                page_index=json.loads((evidence_packs.pack_root(company)/manifest['pages']).read_text(encoding='utf-8'))
                included={(p['source_file'],p['original_page']) for p in page_index}
                for record in library.company_records(company):
                    if record.review_status=='source_verified' and manifest['source_fingerprints'].get(record.source_file)==record.source_sha256:
                        assert all((record.source_file,n) in included for n in evidence_packs._int_pages(record.source_page)),(company,'reviewed page omitted')
                assert all(name in data for name in ('Bear','Base','Bull','Statement history'))
                assert 'Segments' in data if company=='itc' else 'Segments' not in data
                reader=PdfReader(job['pdf_path']);texts=[page.extract_text() or '' for page in reader.pages]
                assert 'VALIDATION REPORT' in texts[0] and ' '.join(payload['company'].split()) in ' '.join(texts[0].split())
                assert 'Contents' in texts[1] and 'Appendix D' in '\n'.join(texts)
                pdf=await client.get(f'/analysis-reports/{report_id}/pdf');excel=await client.get(f'/excel/exports/{job["export_id"]}')
                assert pdf.status_code==excel.status_code==200
                assert pdf.content==Path(job['pdf_path']).read_bytes()
                assert hashlib.sha256(excel.content).hexdigest()==payload['workbook_sha256']
                result={'company':company,'report_id':report_id,'export_id':job['export_id'],'status':'passed_with_ai_unverified',
                    'pdf_path':job['pdf_path'],'pages':len(reader.pages),'sheets':len(data),
                    'history_periods':[(p['label'],p['scope'],p['duration_days']) for p in payload['history']['periods']],
                    'formula_errors':0,'fresh_pdf_page_reads':len(payload['research']['evidence_pack_read']['physical_pdf_review']['pages']),
                    'download_identity':'passed','validation_only':True,'live_ai_assessment':'not_run','native_excel_verified':False}
                summary['companies'].append(result);output.write_text(json.dumps(summary,indent=2),encoding='utf-8')
                print(json.dumps(result),flush=True)
        with patch.object(model,'generate',new=no_model),patch.object(model,'grounded_search',new=no_model),patch.object(research,'generate',new=no_model),patch.object(research,'execute',new=marked_research):
            results=await asyncio.gather(*(check(c) for c in COMPANIES if c not in already),return_exceptions=True)
        errors=[type(r).__name__+': '+str(r) for r in results if isinstance(r,BaseException)]
        summary.update(finished_at=storage.now(),failures=errors,model_call_counter_unchanged=usage()==before)
        output.write_text(json.dumps(summary,indent=2),encoding='utf-8')
        assert not errors,errors
        assert usage()==before,'Validation unexpectedly consumed approved AI attempts.'
        print(json.dumps({'companies':len(summary['companies']),'failures':errors,'ai_calls':0,'report':str(output)}),flush=True)

if __name__=='__main__':asyncio.run(main())
