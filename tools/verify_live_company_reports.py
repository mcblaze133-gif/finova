"""Run normal website API sequentially; retain exact run IDs and honest statuses."""
import json,time,hashlib
from pathlib import Path
import httpx
from backend import storage
OUT=Path('reports/live-company-checks.json')
def save(data):OUT.write_text(json.dumps(data,indent=2),encoding='utf-8')
def main():
 data=json.loads(OUT.read_text()); entries={r['company']:r for r in data['companies']}
 with httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False,timeout=60) as client:
  for company in ('hul','itc','nestle-india','tata-consumer'):
   if company not in entries:
    response=client.post('/analysis-reports',json={'company':company});response.raise_for_status()
    entry={'company':company,**response.json()};data['companies'].append(entry);entries[company]=entry;save(data)
   entry=entries[company]; previous=None
   for _ in range(180):
    response=client.get(entry['status_url']);response.raise_for_status();state=response.json()
    if state['status']!=previous:print(company,state['status'],flush=True);previous=state['status']
    if state['status'] not in ('running','queued'):break
    time.sleep(10)
   else:raise RuntimeError('Report polling deadline reached')
   entry['result']=state
   if state.get('pdf_url'):
    job=storage.rows('SELECT * FROM analysis_reports WHERE id=?',(entry['report_id'],))[0]
    payload=json.loads(job['snapshot_json']);pdf=client.get(state['pdf_url']);excel=client.get(state['excel_url'])
    assert pdf.status_code==excel.status_code==200
    assert pdf.content==Path(job['pdf_path']).read_bytes()
    assert hashlib.sha256(excel.content).hexdigest()==payload['workbook_sha256']
    assert not payload['validation_only']
    raw=payload['research'];update=payload.get('news') or {}
    entry.update(export_id=job['export_id'],pdf_path=job['pdf_path'],download_identity='passed',physical_pdf_pages=len(raw['evidence_pack_read']['physical_pdf_review']['pages']),research_status=storage.rows('SELECT status FROM research_runs WHERE id=?',(job['research_run_id'],))[0]['status'],news_status=update.get('status'),limitations=raw.get('limitations'),coverage=payload.get('coverage'))
   save(data);print(company,json.dumps(entry),flush=True)
 data['finished_at']=storage.now();save(data)
if __name__=='__main__':main()
