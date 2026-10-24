"""Read-only live/data audit, except migrating existing AI usage counters.

Never calls a model, starts a valuation, or outputs credential-bearing settings.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile
import httpx
from backend import storage, model

COMPANIES = ('britannia','hul','itc','nestle-india','tata-consumer')


def main():
    storage.initialize()
    report = {'checked_at':storage.now(),'external_model_calls':0,'checks':[], 'limitations':[]}
    def check(name, passed, **details):
        report['checks'].append({'name':name,'passed':bool(passed),**details})

    with storage.database() as db:
        check('SQLite integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
        check('SQLite foreign keys',not db.execute('PRAGMA foreign_key_check').fetchall())
        active = {table:db.execute(f"SELECT COUNT(*) FROM {table} WHERE status IN ('queued','running','building')").fetchone()[0]
                  for table in ('research_runs','excel_exports','company_update_runs')}
        check('No abandoned active jobs during audit',not any(active.values()),counts=active)
        db.execute('BEGIN IMMEDIATE')
        calls = model._daily_calls(db,storage.now()[:10])
        probes = db.execute('SELECT COUNT(*) FROM model_probes WHERE substr(created_at,1,10)=?',(storage.now()[:10],)).fetchone()[0]
        limit=model._daily_limit(db,storage.now()[:10])
        check('Daily AI cap and explicit extension respected',calls+probes<=limit,calls=calls,probes=probes,normal_cap=model.DAILY_REQUEST_LIMIT,effective_cap=limit)

    failures=[]
    docs=storage.rows('SELECT id,local_path,sha256 FROM documents')
    for row in docs:
        path=(storage.PROJECT_DIR/row['local_path']).resolve()
        valid = path.is_relative_to((storage.DATA_DIR/'raw').resolve()) and path.is_file()
        if valid:
            with path.open('rb') as stream:
                valid = hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256']
        if not valid:
            failures.append(row['id'])
    check('Archived original document hashes',not failures,documents=len(docs),failed_ids=failures)

    exports=storage.rows("SELECT id,workbook_path FROM excel_exports WHERE status='exported'")
    failures=[]
    for row in exports:
        path=Path(row['workbook_path'] or '').resolve()
        try:
            assert path.is_relative_to((storage.PROJECT_DIR/'outputs').resolve()) and path.is_file()
            with ZipFile(path) as archive:
                assert archive.testzip() is None
                assert 'xl/workbook.xml' in archive.namelist()
        except Exception:
            failures.append(row['id'])
    check('All saved Excel exports exist and pass archive integrity',not failures,exports=len(exports),failed_ids=failures)

    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=30,trust_env=False) as client:
        for endpoint in ('/health','/companies','/company-library','/library','/runs','/evaluation','/valuation/methods','/openapi.json'):
            response=client.get(endpoint)
            check('GET '+endpoint,response.status_code==200,status=response.status_code)
        for company in COMPANIES:
            result=client.get('/results/'+company).raise_for_status().json()
            valuation=result.get('valuation') or {}
            check(company+' website valuation',bool(valuation.get('weighted')) and len(valuation.get('methods',[]))>=3 and result['valuation_readiness']['can_build'],
                  numerical_methods=len(valuation.get('methods',[])),missing=result['valuation_readiness']['missing'])
            update=client.get('/updates/'+company).raise_for_status().json()
            data=update.get('result') or {}
            check(company+' online audit recorded',bool(update.get('checked_at') and data),status=update.get('status'),checked_at=update.get('checked_at'),
                  accepted_events=len(data.get('events',[])),news_leads=len(data.get('news_leads',[])))
            if update.get('status') not in ('assessed','assessed_with_unverified_sources'):
                report['limitations'].append(company+': latest online assessment is incomplete; no claim of comprehensive live coverage.')
            if valuation.get('download_url'):
                response=client.get(valuation['download_url'])
                check(company+' Excel download',response.status_code==200 and response.content[:2]==b'PK')
            response=client.get('/evidence/'+company+'/search',params={'q':'revenue'})
            check(company+' cached evidence search',response.status_code==200)
        for endpoint,expected in (('/runs/not-a-valid-id',404),('/documents/-1/original',404),('/excel/exports/not-a-valid-id',404),('/results/not-registered',422),('/evidence/hul/download/invalid',404)):
            response=client.get(endpoint)
            check('Invalid request '+endpoint,response.status_code==expected,status=response.status_code)
        response=client.get('/health',headers={'host':'untrusted.example'})
        check('Foreign Host blocked',response.status_code==403)
        response=client.post('/runs',json={'company':'hul'},headers={'origin':'https://untrusted.example'})
        check('Cross-origin write blocked before job creation',response.status_code==403)
        response=client.post('/excel/exports',json={'company':'../unsafe'})
        check('Unsafe company ID rejected before build',response.status_code==422)

    n8n_path=Path.home()/'.n8n/database.sqlite'
    with sqlite3.connect(n8n_path.as_uri()+'?mode=ro',uri=True) as db:
        matches=[]
        for path in sorted((storage.PROJECT_DIR/'workflows').glob('*.json')):
            expected=json.loads(path.read_text(encoding='utf-8'))
            row=db.execute('SELECT name,active,nodes,connections FROM workflow_entity WHERE id=?',(expected['id'],)).fetchone()
            identical=bool(row and row[0]==expected['name'] and json.loads(row[2])==expected['nodes'] and json.loads(row[3])==expected['connections'])
            check('n8n imported '+expected['name'],identical,active=bool(row[1]) if row else None)
            matches.append(identical)
        report['n8n']={'imported_matches':sum(matches),'exported_workflows':len(matches),'scheduled_automatically':False}
    try:
        with httpx.Client(timeout=10,trust_env=False) as client:
            response=client.get('http://127.0.0.1:5678/healthz')
            check('n8n live health',response.status_code==200)
    except httpx.RequestError:
        check('n8n live health',False)

    report['passed']=all(c['passed'] for c in report['checks'])
    path=storage.PROJECT_DIR/'reports/backend-audit.json'
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']), 'failures':[c for c in report['checks'] if not c['passed']], 'limitations':report['limitations']},indent=2))
    return report['passed']


if __name__=='__main__':
    raise SystemExit(0 if main() else 1)
