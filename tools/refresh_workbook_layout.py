"""Rebuild a finished report's workbook layout without new research/model calls."""
import argparse
import asyncio
import json
import math
import re
from pathlib import Path
from uuid import uuid4
from backend import storage, analysis_reports as reports, excel_engine, evidence_packs


async def main(company, export_id=None):
    jobs=storage.rows("SELECT * FROM analysis_reports WHERE company=? AND status IN ('partial','completed') ORDER BY created_at DESC LIMIT 1",(company,))
    if not jobs:
        raise ValueError('No finished company report is available.')
    job=jobs[0]
    previous=storage.rows('SELECT * FROM excel_exports WHERE id=?',(job['export_id'],))[0]
    package=json.loads(previous['input_json'])
    before=reports.workbook_values(previous['workbook_path'])
    if export_id:
        candidates=storage.rows("SELECT * FROM excel_exports WHERE id=? AND company=? AND status='exported'",(export_id,company))
        if not candidates or json.loads(candidates[0]['input_json'])!=package:
            raise ValueError('Existing export must match the exact frozen report inputs.')
        built={'status':'exported','export_id':export_id}
    else:
        built=await excel_engine.export_package(company,package,force_rebuild=True)
    if built['status']!='exported':
        raise RuntimeError('Layout build failed. Previous report remains available.')
    export=storage.rows('SELECT * FROM excel_exports WHERE id=?',(built['export_id'],))[0]
    after=reports.workbook_values(export['workbook_path'])
    compared=0
    for sheet in ('Dashboard','Bear','Base','Bull','Statement history'):
        for cell,value in before[sheet].items():
            if sheet=='Dashboard' and int(re.search(r'\d+',cell)[0])>=72:
                continue  # Compact chart-source table moves with available input periods.
            if isinstance(value,(int,float)):
                new=after[sheet].get(cell)
                if not isinstance(new,(int,float)) or not math.isclose(value,new,rel_tol=1e-12,abs_tol=1e-8):
                    raise AssertionError((sheet,cell,'Financial value changed'))
                compared+=1
    history=package.get('historical_statements',{}).get('periods',[])
    if history:
        assert list(after)[1]=='Statement history'
        assert len([p for p in history if p['end']])==len(history)
    financials=after['Financials']
    dates=[p for p in package['periods'] if p]
    assert financials['C2']=='Comparable forecast inputs'
    headers=[v for c,v in financials.items() if v is not None and re.fullmatch(r'[E-I]5',c)]
    assert len(headers)==max(1,len(dates)),headers
    if len(dates)==2:
        assert financials.get('G5') is None
    # Preserve the exact research, news timestamps and report ID. Only links/hash
    # change. A presentation repair is not represented as a fresh investigation.
    payload=json.loads(job['snapshot_json'])
    payload['workbook_sha256']=evidence_packs.digest_file(Path(export['workbook_path']))
    payload['workbook_url']=f"http://127.0.0.1:8000/excel/exports/{export['id']}"
    if payload.get('valuation'):
        payload['valuation']['download_url']=f"/excel/exports/{export['id']}"
    payload['revision_note']='Workbook history layout corrected. Research, financial assumptions and online checks retain their stated dates.'
    folder=storage.PROJECT_DIR/'outputs'/job['id']/('layout-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    pdf=await reports.make_pdf(folder,payload)
    backup=storage.PROJECT_DIR/'backups'/('layout-'+uuid4().hex[:8])
    backup.mkdir(parents=True)
    (backup/'report-row.json').write_text(json.dumps(job,indent=2),encoding='utf-8')
    reports.stage(job['id'],'finished',export_id=export['id'],pdf_path=str(pdf),snapshot_json=json.dumps(payload))
    result={'company':company,'report_id':job['id'],'export_id':export['id'],
            'workbook_path':export['workbook_path'],'report_path':str(pdf),
            'numeric_cells_unchanged':compared,'reported_history_periods':len(history),
            'forecast_input_periods':dates,'model_calls_added':0}
    (storage.PROJECT_DIR/'reports'/f'{company}-history-layout.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('company');parser.add_argument('--export-id');args=parser.parse_args()
    asyncio.run(main(args.company,args.export_id))
