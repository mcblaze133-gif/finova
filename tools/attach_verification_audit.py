"""Attach a dated verification register to a finished report; preserve research."""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4
from backend import storage,verification,analysis_reports as reports


async def main(company):
    job=storage.rows("SELECT * FROM analysis_reports WHERE company=? AND status IN ('completed','partial') ORDER BY created_at DESC LIMIT 1",(company,))[0]
    export=storage.rows('SELECT * FROM excel_exports WHERE id=?',(job['export_id'],))[0]
    payload=json.loads(job['snapshot_json']);inputs=json.loads(export['input_json'])
    payload['verification_audit']=verification.build(company,inputs,payload.get('news'),export['workbook_path'],payload['workbook_sha256'])
    folder=storage.PROJECT_DIR/'outputs'/job['id']/('verification-'+uuid4().hex[:8]);folder.mkdir(parents=True)
    target=await reports.make_pdf(folder,payload)
    (folder/'prior-report-row.json').write_text(json.dumps(job),encoding='utf-8')
    reports.stage(job['id'],'finished',pdf_path=str(target),snapshot_json=json.dumps(payload))
    print(json.dumps({'company':company,'report_id':job['id'],'pdf_path':str(target),
        'verification_records':payload['verification_audit']['input_records'],
        'integrity_and_review_passed':payload['verification_audit']['integrity_and_review_passed'],
        'model_calls_added':0,'financial_inputs_changed':False},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('company');args=parser.parse_args()
    asyncio.run(main(args.company))
