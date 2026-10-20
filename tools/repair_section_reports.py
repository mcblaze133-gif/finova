"""Continue existing report research without relabelling old news as freshly checked."""
import asyncio,json
from pathlib import Path
from backend import storage,analysis_reports as ar,sector_research,research_gaps

async def main():
 source=json.loads(Path('reports/live-company-checks.json').read_text());checks=[]
 for entry in source['companies']:
  rid=entry['report_id'];job=ar.row(rid);folder=Path(job['pdf_path']).parent
  payload=json.loads(job['snapshot_json']);run_id=job['research_run_id']
  print(entry['company'],'section research started',flush=True)
  ar.stage(rid,'section_analysis',status='running')
  try:
   audit=await sector_research.complete(payload,run_id)
   payload['coverage']=research_gaps.report_coverage(payload)
   payload['generated_at']=storage.now()
   payload['revision_note']='Supplemental operating research updated '+storage.now()+'. Financial inputs and the online-update check retain their separately stated dates.'
   path=await ar.make_pdf(folder,payload)
   ar.stage(rid,'finished',status='partial',pdf_path=str(path),snapshot_json=json.dumps(payload))
   result={'company':entry['company'],'report_id':rid,'status':audit['status'],'areas':[{k:a.get(k) for k in ('topic','status','review_reason','gaps')} for a in audit['areas']],'error':audit.get('error'),'pdf_path':str(path),'model_calls':payload['research'].get('model_calls')}
   checks.append(result);Path('reports/section-repair-checks.json').write_text(json.dumps(checks,indent=2))
   print(json.dumps(result),flush=True)
  except BaseException:
   ar.stage(rid,'failed',status='failed',error='Section report revision failed; see saved audit.')
   raise
if __name__=='__main__':asyncio.run(main())
