"""Publish matching PDF/Excel research sets using frozen reviewed financial inputs."""
import asyncio,json,hashlib
from uuid import uuid4
from pathlib import Path
from backend import storage,model,analysis_reports as ar,excel_engine,report_excel,research_gaps

async def main():
 if storage.rows("SELECT id FROM analysis_reports WHERE status IN ('queued','running')"):raise RuntimeError('An investigation is active.')
 summary=json.loads(Path('reports/live-company-checks.json').read_text());checks=[]
 with storage.database() as db:before=model._daily_calls(db,storage.now()[:10])
 for e in summary['companies']:
  rid=e['report_id'];job=ar.row(rid);old=json.loads(job['snapshot_json']);old_export=storage.rows('SELECT * FROM excel_exports WHERE id=?',(job['export_id'],))[0]
  package=json.loads(old_export['input_json']);old_values=ar.workbook_values(old_export['workbook_path'])
  if package.get('research_report'):
   print(e['company'],'already integrated',flush=True);continue
  print(e['company'],'building integrated workbook',flush=True);ar.stage(rid,'workbook_research',status='running',error=None)
  try:
   report_excel.attach(package,rid);package['created_at']=storage.now();export_id=uuid4().hex
   result=await excel_engine.export_package(e['company'],package,export_id,force_rebuild=True)
   if result['status']!='exported':raise ValueError('Integrated workbook build failed.')
   new_path=Path('outputs',export_id,'SignalAI_FMCG_Valuation.xlsx');new_values=ar.workbook_values(new_path)
   for sh in ('Dashboard','Bear','Base','Bull','Statement history'):
    for cell,value in old_values[sh].items():
     if isinstance(value,(int,float)):
      assert new_values[sh].get(cell)==value,(e['company'],sh,cell,'financial result changed')
   payload=ar.snapshot(e['company'],job['research_run_id'],export_id,rid)
   payload['targeted_research']=old.get('targeted_research',{})
   payload['coverage']=research_gaps.report_coverage(payload)
   payload['revision_note']='Research and editable valuation workbook prepared together. Financial sources and the online-update check retain their stated dates.'
   assert payload['research_excel_linked']
   path=await ar.make_pdf(Path(job['pdf_path']).parent,payload)
   ar.stage(rid,'finished',status='partial',export_id=export_id,pdf_path=str(path),snapshot_json=json.dumps(payload))
   e.update(export_id=export_id,pdf_path=str(path),research_excel_linked=True)
   checks.append({'company':e['company'],'report_id':rid,'export_id':export_id,'financials_unchanged':True,'research_notes':len(package['research_notes']),'pdf_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
   Path('reports/report-workbook-integration.json').write_text(json.dumps(checks,indent=2))
   Path('reports/live-company-checks.json').write_text(json.dumps(summary,indent=2))
   print(json.dumps(checks[-1]),flush=True)
  except BaseException:
   ar.stage(rid,'failed',status='failed',error='The integrated research workbook could not be prepared; no older result was substituted.')
   raise
 with storage.database() as db:assert before==model._daily_calls(db,storage.now()[:10])
 print('All integrated; no model requests used',flush=True)
if __name__=='__main__':asyncio.run(main())
