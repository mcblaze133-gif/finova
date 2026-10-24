"""Correct a named report set, preserving financial values and news dates.

This is an explicitly labelled revision, never a fresh investigation. Originals
and database rows are backed up. No saved Excel file is overwritten.
"""
import argparse
import asyncio
import json
import math
from pathlib import Path
from uuid import uuid4
from backend import storage,model,analysis_reports as ar,excel_engine,report_excel,research_gaps,sector_comparison,sector_research,evidence_packs


async def main(companies,reassess):
    if storage.rows("SELECT id FROM analysis_reports WHERE status IN ('queued','running')"):
        raise ValueError('An investigation is active; wait before revising reports.')
    if reassess:model.require_capacity(3*len(reassess))
    checks=[]
    for company in companies:
        job=storage.rows("SELECT * FROM analysis_reports WHERE company=? AND status IN ('completed','partial') AND snapshot_json IS NOT NULL ORDER BY created_at DESC LIMIT 1",(company,))[0]
        old=json.loads(job['snapshot_json']);run=storage.rows('SELECT * FROM research_runs WHERE id=?',(job['research_run_id'],))[0]
        previous=storage.rows('SELECT * FROM excel_exports WHERE id=?',(job['export_id'],))[0]
        package=excel_engine.company_package(company,update_run_id=old['research'].get('update_run_id'))
        frozen=json.loads(previous['input_json'])
        for key in ('financials','assumptions','market','methods','segments'):
            if package[key]!=frozen[key]:raise ValueError(company+': '+key+' changed; a labelled artifact revision cannot silently update financial inputs.')
        read=old['research']['evidence_pack_read'];manifest=evidence_packs.read_manifest(company)
        if read['signature']!=manifest['signature'] or manifest['source_fingerprints']!=evidence_packs.source_fingerprints(company):
            raise ValueError(company+': evidence changed; run a fresh investigation instead.')
        revision=uuid4().hex;backup=storage.PROJECT_DIR/'backups'/('sector-revision-'+revision);backup.mkdir(parents=True)
        (backup/'report-row.json').write_text(json.dumps(job,indent=2),encoding='utf-8')
        (backup/'research-row.json').write_text(json.dumps(run,indent=2),encoding='utf-8')
        before=ar.workbook_values(previous['workbook_path'])
        print(company,'building labelled correction',flush=True)
        try:
            ar.stage(job['id'],'evidence_correction',status='running',error=None)
            if company in reassess:
                raw=json.loads(run['report_json'])
                await sector_research.complete({'company_id':company,'company':old['company'],'research':raw,
                    'history':old['history'],'targeted_research':old.get('targeted_research',{})},job['research_run_id'])
            report_excel.attach(package,job['id'])
            built=await excel_engine.export_package(company,package,force_rebuild=True)
            if built['status']!='exported':raise ValueError('Corrected workbook did not export.')
            export=storage.rows('SELECT * FROM excel_exports WHERE id=?',(built['export_id'],))[0]
            after=ar.workbook_values(export['workbook_path']);count=0
            for sheet in ('Dashboard','Bear','Base','Bull','Statement history'):
                for cell,value in before[sheet].items():
                    if isinstance(value,(int,float)):
                        new=after[sheet].get(cell)
                        if not isinstance(new,(int,float)) or not math.isclose(value,new,rel_tol=1e-12,abs_tol=1e-8):
                            raise ValueError(company+': financial result changed at '+sheet+'!'+cell)
                        count+=1
            payload=ar.snapshot(company,job['research_run_id'],export['id'],job['id'])
            payload['targeted_research']=old.get('targeted_research',{})
            payload['coverage']=research_gaps.report_coverage(payload)
            payload['revision_note']='Reviewed peer and operating evidence updated. Main financial assumptions and scenario values are unchanged. The online check retains its stated earlier date; this revision did not run a new news search.'
            payload['revision_id']=revision
            folder=storage.PROJECT_DIR/'outputs'/job['id']/('revision-'+revision);folder.mkdir(parents=True)
            pdf=await ar.make_pdf(folder,payload)
            ar.stage(job['id'],'finished',status='partial',export_id=export['id'],pdf_path=str(pdf),snapshot_json=json.dumps(payload))
            checks.append({'company':company,'report_id':job['id'],'export_id':export['id'],'revision_id':revision,
                           'news_checked_at':(payload.get('news') or {}).get('checked_at'),'new_news_check':False,
                           'numeric_cells_unchanged':count,'operating_benchmarks':len(payload['sector_comparison']['rows']),
                           'report_path':str(pdf),'workbook_path':export['workbook_path']})
            (storage.PROJECT_DIR/'reports/sector-revisions.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
            print(company,'correction published; financial values unchanged:',count,flush=True)
        except BaseException:
            # Failed correction restores the prior delivered report row; it is
            # not represented as a successful fresh investigation.
            with storage.database() as db:
                db.execute('UPDATE research_runs SET report_json=? WHERE id=?',(run['report_json'],job['research_run_id']))
                db.execute('UPDATE analysis_reports SET status=?,stage=?,error=?,export_id=?,pdf_path=?,snapshot_json=?,updated_at=? WHERE id=?',
                           (job['status'],job['stage'],job['error'],job['export_id'],job['pdf_path'],job['snapshot_json'],job['updated_at'],job['id']))
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--companies',nargs='+',required=True);parser.add_argument('--reassess',nargs='*',default=[]);args=parser.parse_args()
    if not set(args.reassess)<=set(args.companies):parser.error('Reassessment companies must be in the revision set.')
    asyncio.run(main(args.companies,set(args.reassess)))
