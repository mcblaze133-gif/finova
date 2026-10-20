"""Rebuild and publish five historical packs with two bounded local workers.

No network/model calls. Each worker verifies copied source pages before publishing.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import subprocess
import sys
from backend import storage,evidence_packs
from tools.prepare_all_company_evidence import prepare,publish,write_text

COMPANIES=('britannia','hul','itc','nestle-india','tata-consumer')


def worker(company):
    result=prepare(company)
    if result['status']!='prepared':raise ValueError('No prepared evidence pack.')
    publish(result)
    manifest=evidence_packs.read_manifest(company)
    result['history_policy']=manifest['history_policy']
    result['represented_documents']=sum(bool(d['selected_original_pages']) for d in manifest['source_index'])
    result['duplicate_documents']=sum(bool(d.get('duplicate_of')) for d in manifest['source_index'])
    write_text(storage.PROJECT_DIR/'reports'/f'historical-evidence-{company}.json',json.dumps(result,indent=2))
    return result


def launch(company):
    process=subprocess.run([sys.executable,'-u','-m','tools.upgrade_historical_evidence','--worker',company],
                           cwd=storage.PROJECT_DIR,capture_output=True,text=True,encoding='utf-8')
    if process.returncode:
        return {'company':company,'status':'failed','error':process.stderr[-1500:]}
    return json.loads(process.stdout.strip().splitlines()[-1])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',choices=COMPANIES)
    args=parser.parse_args()
    storage.initialize()
    if args.worker:
        print(json.dumps(worker(args.worker)),flush=True)
        return
    summary={'created_at':storage.now(),'model_calls':0,'companies':[]}
    path=storage.PROJECT_DIR/'reports/historical-evidence-upgrade.json'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(launch,c):c for c in COMPANIES}
        print('Rebuilding historical evidence for five companies; two local workers.',flush=True)
        for future in as_completed(futures):
            result=future.result()
            summary['companies'].append(result)
            write_text(path,json.dumps(summary,indent=2))
            print(json.dumps({k:result[k] for k in ('company','status','selected_pages','represented_documents') if k in result}),flush=True)
    if any(r['status']!='prepared' for r in summary['companies']):raise SystemExit(1)


if __name__=='__main__':main()
