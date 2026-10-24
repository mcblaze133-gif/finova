"""Read back the exact five report/Excel/PDF outputs of a named live audit.

Does not create reports or consume model attempts. Reports remain qualified.
"""
import argparse
import json
import math
from pathlib import Path
import httpx
from backend import analysis_reports as ar,storage
from tools.verify_fresh_company_reports import inspect_report


def check_metrics(peer,cells,index):
    values=peer['values']
    for metric,column,numerator,denominator in [('revenue_growth','E',None,'prior_revenue'),
            ('ebitda_margin','F','ebitda','revenue'),('cash_conversion','G','cfo','net_income'),
            ('capex_ratio','H','capex','revenue'),('net_debt_sales','I',None,'revenue')]:
        actual=cells.get(f'{column}{index}')
        if metric=='revenue_growth':
            expected=values['revenue']/values['prior_revenue']-1 if values.get('prior_revenue',0)>0 else None
        elif metric=='net_debt_sales':
            expected=(values['debt']-values['cash'])/values['revenue'] if all(k in values for k in ('debt','cash')) and values['revenue']>0 else None
        else:
            expected=values[numerator]/values[denominator] if numerator in values and values.get(denominator,0)>0 else None
        if expected is None:assert actual=='n.a.',(peer['company_id'],metric,'missing must not be zero')
        else:assert isinstance(actual,(int,float)) and math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-10),(peer['company_id'],metric)
        assert peer['metrics'][metric]==actual,'PDF/website metric differs from saved Excel result'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--audit',type=Path,required=True);args=parser.parse_args()
    data=json.loads(args.audit.read_text(encoding='utf-8'))
    expected={c['id'] for c in json.loads((storage.PROJECT_DIR/'config/sector_universe.json').read_text(encoding='utf-8'))['companies']}
    assert {e['company'] for e in data['companies']}==expected,'Audit does not cover the scoped five companies'
    checks=[]
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=120,trust_env=False) as client:
        for entry in data['companies']:
            # An explicitly labelled revision can update artifacts on the same
            # report ID. Re-read that exact ID, never select a different run.
            state=client.get(f"/analysis-reports/{entry['report_id']}").raise_for_status().json()
            assert state['id']==entry['report_id'] and state['company']==entry['company']
            entry['result']=state
            inspect_report(client,entry)
            job=ar.row(entry['report_id']);payload=json.loads(job['snapshot_json']);peer_data=payload['sector_comparison']
            workbook=ar.workbook_values(storage.rows('SELECT workbook_path FROM excel_exports WHERE id=?',(job['export_id'],))[0]['workbook_path'])
            assert {p['company_id'] for p in peer_data['rows']}==expected
            assert sum(bool(p['subject']) for p in peer_data['rows'])==1
            assert next(p['company_id'] for p in peer_data['rows'] if p['subject'])==entry['company']
            for index,peer in enumerate(peer_data['rows'],6):check_metrics(peer,workbook['Sector comparison'],index)
            findings=client.get(f"/analysis-reports/{entry['report_id']}/findings").raise_for_status().json()
            assert findings['company_id']==entry['company'] and findings['report_id']==entry['report_id']
            assert len(findings['sector_comparison']['rows'])==len(expected)
            cards=[*findings['cards'],*findings['business'],*findings['updates']]
            assert cards and all(c['sources'] and c['verification_label'] and not c['verified'] for c in cards)
            for peer in findings['sector_comparison']['rows']:
                assert peer['sources']
                with client.stream('GET',peer['sources'][0]['url'].split('#')[0]) as response:
                    response.raise_for_status();assert response.headers.get('content-type','').startswith('application/pdf')
            checks.append({'company':entry['company'],'report_id':entry['report_id'],'export_id':job['export_id'],
                           'delivery_checks_passed':True,'excel_peer_ratios_checked':5*len(expected),'source_linked_cards':len(cards),
                           'operating_benchmark_rows':len(expected),'independently_verified_discoveries':findings['verified_discoveries'],
                           'news_status':entry['news_status'],'coverage_complete':entry['research_complete']})
            print(entry['company'],'exact report / Excel / PDF / source checks passed',flush=True)
    path=storage.PROJECT_DIR/'reports/sector-output-verification.json'
    path.write_text(json.dumps({'checked_at':storage.now(),'audit':str(args.audit),'companies':checks},indent=2),encoding='utf-8')


if __name__=='__main__':main()
