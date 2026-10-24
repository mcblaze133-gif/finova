"""Coverage register of exact delivered reports, not a new investigation."""
import hashlib
import json
from pathlib import Path
from backend import storage, discovery_view
from backend.companies import resolve


def build():
    universe=json.loads((storage.PROJECT_DIR/'config/sector_universe.json').read_text(encoding='utf-8'))
    entries=[]
    for item in universe['companies']:
        company=item['id']
        active=storage.rows("SELECT id FROM analysis_reports WHERE company=? AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",(company,))
        jobs=storage.rows("SELECT * FROM analysis_reports WHERE company=? AND status IN ('completed','partial') AND snapshot_json IS NOT NULL ORDER BY created_at DESC LIMIT 1",(company,))
        entry={'company_id':company,'company':resolve(company).legal_name,'role':item['role'],
               'active_report_id':active[0]['id'] if active else None,'delivered_report_id':None,'checks_passed':False}
        if jobs:
            job=jobs[0];p=json.loads(job['snapshot_json']);rid=job['id']
            exports=storage.rows("SELECT * FROM excel_exports WHERE id=? AND company=? AND status='exported'",(job['export_id'],company))
            identity=p.get('company_id')==company and p.get('report_id')==rid
            workbook_ok=False
            if exports and exports[0]['workbook_path']:
                path=Path(exports[0]['workbook_path'])
                if path.is_file():workbook_ok=hashlib.sha256(path.read_bytes()).hexdigest()==p.get('workbook_sha256')
            pdf_ok=bool(job['pdf_path'] and Path(job['pdf_path']).is_file())
            findings=discovery_view.build(p) if identity else {}
            cards=[*findings.get('cards',[]),*findings.get('business',[]),*findings.get('updates',[])]
            linked=bool(cards) and all(c.get('sources') and c.get('verification_label') for c in cards)
            operating=[a for a in p.get('coverage',{}).get('areas',[]) if a['area'] not in ('Financial statements','Conditional valuation','Current developments','Corroborated discovery')]
            entry.update(delivered_report_id=rid,prepared_at=p.get('generated_at'),report_status=job['status'],
                checks_passed=bool(identity and workbook_ok and pdf_ok and linked and p.get('research_excel_linked')),
                checks={'report_identity':identity,'workbook_hash':workbook_ok,'pdf_present':pdf_ok,'source_linked_findings':linked,'research_excel_linked':bool(p.get('research_excel_linked'))},
                operating_complete=sum(a.get('status')=='complete' for a in operating),operating_total=len(operating),
                unresolved_areas=[a['area'] for a in p.get('coverage',{}).get('areas',[]) if a.get('status')!='complete'],
                history_periods=len(p.get('history',{}).get('periods',[])),
                operating_benchmark_rows=len((p.get('sector_comparison') or {}).get('rows',[])),
                verified_discoveries=findings.get('verified_discoveries',0),news_checked_at=(p.get('news') or {}).get('checked_at'),
                report_url=f'/#report-{rid}',pdf_url=f'/analysis-reports/{rid}/pdf',excel_url=f'/excel/exports/{job["export_id"]}',
                verification_url=f'/analysis-reports/{rid}/verification/view')
        entries.append(entry)
    return {'checked_at':storage.now(),'universe':universe,'companies':entries,
            'all_delivery_checks_passed':all(e['checks_passed'] for e in entries),
            'meaning':'Delivery checks establish report identity, artifact integrity and source-link presence. They do not establish complete research, issuer authenticity, independent corroboration or validated peer multiples. Active investigations are separate from the explicitly dated delivered reports.'}
