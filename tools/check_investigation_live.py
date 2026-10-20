"""One bounded real investigation; obeys the normal persisted model quota."""
import asyncio
import json
import sys
import httpx
from backend import storage


async def main(company,fresh=False):
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',timeout=30,trust_env=False) as client:
        response=await client.post('/investigations' if fresh else '/runs',json={'company':company} if fresh else {'company':company,'refresh':True,'max_documents':1})
        response.raise_for_status()
        job=response.json()
        print(json.dumps({'run_id':job['run_id'],'status':'started'}),flush=True)
        last=None
        for _ in range(400):
            await asyncio.sleep(2)
            state=(await client.get(job['status_url'])).raise_for_status().json()
            marker=(state['status'],state['stage'],state['model_calls'])
            if marker!=last:
                print(json.dumps({'status':marker[0],'stage':marker[1],'model_calls':marker[2]}),flush=True)
                last=marker
            if state['status'] not in ('queued','running'):
                report=(await client.get('/runs/'+job['run_id']+'/report')).raise_for_status().json()
                results=(await client.get(job['report_url'] if fresh else '/results/'+company)).raise_for_status().json()
                evidence=report.get('discovery_checks',{})
                summary={'run_id':job['run_id'],'company':company,'status':state['status'],
                         'model_calls':state['model_calls'],'hypotheses':report.get('hypotheses',[]),
                         'targeted_searches':report.get('research_plan_execution',[]),
                         'admitted':evidence.get('admitted',False),'evidence_strength':report.get('evidence_strength'),
                         'limitations':report.get('limitations',[]),
                         'website_report_present':bool(results.get('investigation')),
                         'freshness':results.get('freshness'),'evidence_pack_read':report.get('evidence_pack_read'),
                         'website_report':results.get('investigation')}
                filename='investigation-fresh-live-check.json' if fresh else 'investigation-live-check.json'
                (storage.PROJECT_DIR/'reports'/filename).write_text(json.dumps(summary,indent=2),encoding='utf-8')
                print(json.dumps({k:v for k,v in summary.items() if k not in ('website_report','hypotheses','targeted_searches')},indent=2),flush=True)
                return
        raise RuntimeError('Investigation did not reach a terminal status within the audit polling window.')


if __name__=='__main__':
    asyncio.run(main(sys.argv[1] if len(sys.argv)>1 else 'hul','--fresh' in sys.argv))
