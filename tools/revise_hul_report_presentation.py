"""Refresh presentation from frozen inputs; retain the original news check date."""
import asyncio
import json
import shutil
from pathlib import Path
from uuid import uuid4

from backend import analysis_reports as ar, excel_engine, report_excel, research_gaps, storage


async def main():
    rid = 'a40db7bc6b0f4e78b0308323ee55af77'
    job = ar.row(rid)
    if job['status'] not in ('partial', 'completed'):
        raise ValueError('Report must be finished before revising it.')
    old = json.loads(job['snapshot_json'])
    run = storage.rows('SELECT report_json FROM research_runs WHERE id=?', (job['research_run_id'],))[0]
    raw = json.loads(run['report_json'])
    old_export = storage.rows('SELECT * FROM excel_exports WHERE id=?', (job['export_id'],))[0]
    package = json.loads(old_export['input_json'])
    before = ar.workbook_values(old_export['workbook_path'])
    folder = Path(job['pdf_path']).parent
    backup = folder / ('presentation-before-' + uuid4().hex[:8])
    backup.mkdir()
    shutil.copy2(job['pdf_path'], backup / 'report.pdf')
    shutil.copy2(folder / 'research-report-inputs.json', backup / 'inputs.json')
    (backup / 'research.json').write_text(run['report_json'], encoding='utf-8')
    # A controls disclosure that says no material conflicts is not evidence of
    # actual governance scrutiny. Correct the source context in both outputs.
    for sections in (raw.get('sector_sections', []), raw.get('section_analysis', {}).get('areas', [])):
        for section in sections:
            if section['topic'] != 'Costs and profitability':
                continue
            section['statements'][0]['text'] = 'For the specified related-party raw-material transactions, the disclosed pricing framework combines cost-plus markups and market benchmarking. This does not describe all HUL procurement. Separately, management described maintaining EBITDA margins despite inflationary headwinds in the March 2022 results.'
            section['counterevidence']['text'] = 'The cited annual report states that no material financial or commercial transaction between the company and Management Committee members created a potential conflict of interest. This is a disclosed control statement; it does not independently establish that all related-party prices are economically optimal.'
            section['review_reason'] = 'Source-context clarification: pricing terms apply to the specified related-party arrangements, and the controls disclosure reports no material conflicts. It is not evidence of actual misconduct.'
    try:
        with storage.database() as db:
            db.execute('UPDATE research_runs SET report_json=?,updated_at=? WHERE id=?', (json.dumps(raw), storage.now(), job['research_run_id']))
        # Remove the previous generated research prefix before attaching the
        # revised findings. Preserve the original company and news notes.
        start = next(i for i, n in enumerate(package['research_notes']) if n['topic'] == 'Continuing earnings')
        package['research_notes'] = package['research_notes'][start:]
        package.pop('research_report', None)
        report_excel.attach(package, rid)
        package['created_at'] = storage.now()
        eid = uuid4().hex
        built = await excel_engine.export_package('hul', package, eid, force_rebuild=True)
        if built['status'] != 'exported':
            raise ValueError('Workbook revision failed.')
        updated_export = storage.rows('SELECT * FROM excel_exports WHERE id=?', (eid,))[0]
        after = ar.workbook_values(updated_export['workbook_path'])
        for sheet in ('Dashboard', 'Bear', 'Base', 'Bull', 'Statement history'):
            for cell, value in before[sheet].items():
                if isinstance(value, (int, float)):
                    assert after[sheet].get(cell) == value, (sheet, cell, 'Financial result changed')
        payload = ar.snapshot('hul', job['research_run_id'], eid, rid)
        payload['targeted_research'] = old.get('targeted_research', {})
        payload['coverage'] = research_gaps.report_coverage(payload)
        payload['revision_note'] = 'Presentation revised; financial assumptions and the online review retain their stated dates.'
        path = await ar.make_pdf(folder, payload)
        ar.stage(rid, 'finished', status='partial', export_id=eid, pdf_path=str(path), snapshot_json=json.dumps(payload), error=None)
        summary = {'report_id': rid, 'export_id': eid, 'pdf_path': str(path), 'workbook_path': updated_export['workbook_path'], 'financial_values_unchanged': True, 'news_checked_at': payload['news']['checked_at'], 'model_calls_added': 0}
        (storage.PROJECT_DIR / 'reports/hul-presentation-revision.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps(summary), flush=True)
    except BaseException:
        with storage.database() as db:
            db.execute('UPDATE research_runs SET report_json=? WHERE id=?', (run['report_json'], job['research_run_id']))
        shutil.copy2(backup / 'report.pdf', job['pdf_path'])
        shutil.copy2(backup / 'inputs.json', folder / 'research-report-inputs.json')
        raise


if __name__ == '__main__':
    asyncio.run(main())
