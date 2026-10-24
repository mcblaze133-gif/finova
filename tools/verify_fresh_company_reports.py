"""Test the real website pipeline for all populated companies.

Every invocation starts new jobs. --resume resumes only exact recorded IDs,
never 'latest' reports. Existing free-tier and admission controls remain active.
"""
import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from backend import analysis_reports, storage, model

COMPANIES = ('britannia', 'hul', 'itc', 'nestle-india', 'tata-consumer')


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def poll(client, url):
    """Retry only idempotent status reads, never a job-creating POST."""
    for attempt in range(4):
        try:
            return client.get(url).raise_for_status().json()
        except httpx.TransportError:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def inspect_report(client, entry):
    job = analysis_reports.row(entry['report_id'])
    payload = json.loads(job['snapshot_json'] or '{}')
    state = entry['result']
    if not state.get('pdf_url'):
        raise ValueError('New investigation produced no downloadable report: ' + str(state.get('error')))
    assert payload['company_id'] == entry['company']
    assert not payload.get('validation_only'), 'Validation-only report cannot pass live audit'
    assert job['created_at'] >= entry['requested_at']
    raw = payload['research']
    update_id = raw.get('update_run_id')
    update = storage.rows('SELECT * FROM company_update_runs WHERE id=?', (update_id,))
    assert update and update[0]['company'] == entry['company']
    assert update[0]['created_at'] >= entry['requested_at'], 'Earlier news check reused'
    physical = raw['evidence_pack_read']['physical_pdf_review']
    assert physical['pages'], 'No physical evidence-PDF pages read'
    pdf = client.get(state['pdf_url']).raise_for_status()
    excel = client.get(state['excel_url']).raise_for_status()
    assert pdf.content == Path(job['pdf_path']).read_bytes()
    assert hashlib.sha256(excel.content).hexdigest() == payload['workbook_sha256']
    reader = client.get(state['view_url'], timeout=150).raise_for_status()
    assert f'/analysis-reports/{entry["report_id"]}/pages/1' in reader.text
    assert f'/excel/exports/{job["export_id"]}' in reader.text
    cover = client.get(f'/analysis-reports/{entry["report_id"]}/pages/1').raise_for_status()
    assert cover.headers['content-type'].startswith('image/png')
    assert cover.content.startswith(b'\x89PNG\r\n\x1a\n')
    audit = client.get(f"/analysis-reports/{entry['report_id']}/verification").raise_for_status().json()
    assert audit == payload['verification_audit'], 'Register differs from frozen report'
    human = client.get(state['verification_url']).raise_for_status()
    assert 'matching file hashes' in human.text
    export = storage.rows('SELECT * FROM excel_exports WHERE id=?', (job['export_id'],))[0]
    inputs = json.loads(export['input_json'])
    assert inputs['research_report']['report_id'] == entry['report_id']
    workbook = analysis_reports.workbook_values(export['workbook_path'])
    for sheet in ('Dashboard', 'Statement history', 'Sources', 'Bear', 'Base', 'Bull'):
        assert sheet in workbook, f'Missing {sheet}'
    assert ('Segments' in workbook) == bool(inputs.get('segments'))
    assert payload['history']['periods'], 'Historical statements missing'
    news_result = (payload.get('news') or {}).get('result') or {}
    entry.update(
        checks_passed=True, export_id=job['export_id'], pdf_path=job['pdf_path'],
        workbook_path=export['workbook_path'], update_id=update_id,
        news_status=(payload.get('news') or {}).get('status'),
        news_checked_at=(payload.get('news') or {}).get('checked_at'),
        physical_pdf_pages=len(physical['pages']),
        history_periods=len(payload['history']['periods']),
        reviewed_inputs=audit['integrity_and_review_passed'], source_inputs=audit['input_records'],
        verification_systems=audit['systems'], coverage=payload.get('coverage', {}),
        research_limitations=raw.get('limitations'), valuation=payload['valuation'].get('weighted'),
        research_complete=bool(payload.get('coverage', {}).get('complete')),
        server_duration_seconds=round((datetime.fromisoformat(job['updated_at'])-datetime.fromisoformat(job['created_at'])).total_seconds(), 1),
        original_sources_read=sum(c.get('status') == 'original_read' for c in news_result.get('primary_source_coverage', [])),
        news_leads=len(news_result.get('news_leads', [])), peer_rows=len(inputs.get('peers', [])),
        transaction_rows=len(inputs.get('transactions', [])),
        weighted_methods=[m['method'] for m in inputs['methods'] if m.get('weight', 0)],
        valuation_date=payload['valuation'].get('valuation_date'),
        market_price_date=payload['valuation'].get('market_price_date'),
        website_reader_checked=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--companies', nargs='+', choices=COMPANIES, default=list(COMPANIES))
    args = parser.parse_args()
    storage.initialize()
    path = args.resume or Path('reports') / f'live-companies-{uuid4().hex}.json'
    data = json.loads(path.read_text(encoding='utf-8')) if args.resume else {
        'started_at': storage.now(), 'companies': [], 'planned_companies': args.companies,
        'validation_only': False,
    }
    data.pop('finished_at', None)
    save(path, data)
    print('Audit file:', path, flush=True)
    entries = {r['company']: r for r in data['companies']}
    with httpx.Client(base_url='http://127.0.0.1:8000', trust_env=False, timeout=60) as client:
        client.get('/verification/hul').raise_for_status()
        for company in data['planned_companies']:
            entry = entries.get(company)
            if entry and entry.get('finished_at') and (entry.get('checks_passed') or not args.retry_failed):
                continue
            if entry:
                entry.pop('error', None)
                entry.pop('finished_at', None)
            if not entry:
                entry = {'company': company, 'requested_at': storage.now()}
                data['companies'].append(entry)
                save(path, data)
            try:
                if not entry.get('report_id'):
                    response = client.post('/analysis-reports', json={'company': company})
                    response.raise_for_status()
                    entry.update(response.json())
                    save(path, data)
                previous = None
                deadline = time.monotonic() + 1800
                while time.monotonic() < deadline:
                    state = poll(client, entry['status_url'])
                    if state['status'] != previous:
                        print(company, state['status'], flush=True)
                        previous = state['status']
                    entry['result'] = state
                    save(path, data)
                    if state['status'] not in ('running', 'queued'):
                        break
                    time.sleep(5)
                else:
                    raise TimeoutError('Job still active; resume this audit, do not start a duplicate')
                inspect_report(client, entry)
            except Exception as exc:
                entry.update(checks_passed=False, error=f'{type(exc).__name__}: {exc}')
                print(company, 'CHECK FAILED:', entry['error'], flush=True)
                if isinstance(exc, (TimeoutError, httpx.TransportError)):
                    # An interrupted read says nothing about job completion.
                    # Stop here so a later company cannot collide with it.
                    save(path, data)
                    raise
            entry['finished_at'] = storage.now()
            save(path, data)
            print(company, 'checks:', entry.get('checks_passed'), 'report:', entry.get('report_id'),
                  'news:', entry.get('news_status'), flush=True)
    with storage.database() as db:
        data['daily_model_calls'] = model._daily_calls(db, storage.now()[:10])
        data['daily_cap'] = model._daily_limit(db, storage.now()[:10])
    data['finished_at'] = storage.now()
    data['all_pipeline_checks_passed'] = all(e.get('checks_passed') for e in data['companies']) and len(data['companies']) == len(data['planned_companies'])
    save(path, data)
    print('Finished:', path, flush=True)
    if not data['all_pipeline_checks_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
