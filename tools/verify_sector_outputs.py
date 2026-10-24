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


def check_valuation_peers(payload,workbook):
    peers=payload.get('peer_valuation')
    assert peers,'Reviewed comparison missing from new report'
    cells=workbook['Peer valuation'];selected=[]
    for r,item in enumerate(peers['companies'],21):
        v=item['values'];tax=v['tax']/v['pbt']
        expected=(v['pat']-v['exceptional_credit']*(1-tax)*item['owner_allocation']-
                  v['oneoff_tax_credit']*item['owner_allocation'])/1e7
        assert math.isclose(cells[f'AB{r}'],expected,abs_tol=1e-6)
        assert math.isclose(item['metrics']['adjusted_pe'],v['market_cap']/(expected*1e7),rel_tol=1e-10)
        assert cells[f'D{r}']==('Yes' if item['included'] else 'No')
        assert not(item['subject'] and item['included'])
        if item['included']:selected.append(item)
        raw_ebitda=v['ebitda']
        if raw_ebitda is None:raw_ebitda=v['pbt']-v['exceptional_credit']+v['finance_cost']+v['da']-v['other_income']
        assert math.isclose(cells[f'AA{r}'],(raw_ebitda+v['ebitda_addback'])/1e7,abs_tol=1e-6)
        bridge=('market_cap','debt','nci','preferred','other_claims','cash','nonoperating_assets')
        if all(isinstance(v.get(k),(int,float)) for k in bridge):
            ev=(v['market_cap']+v['debt']+v['nci']+v['preferred']+v['other_claims']-v['cash']-v['nonoperating_assets'])/1e7
            assert math.isclose(cells[f'AC{r}'],ev,abs_tol=1e-6)
            assert math.isclose(item['metrics']['ev_ebitda'],ev/cells[f'AA{r}'],rel_tol=1e-10)
        else:assert item['metrics']['ev_ebitda']=='n.a.'
    subject=next((r,item) for r,item in enumerate(peers['companies'],21) if item['subject'])
    sr,subject=subject;shares=subject['values']['shares']
    for key,metric,anchor,output in [('pe','adjusted_pe',11,6),('ev_ebitda','ev_ebitda',12,7)]:
        values=[p['metrics'][metric] for p in selected if isinstance(p['metrics'][metric],(int,float))]
        assert cells[f'G{anchor}']==len(values)
        result=peers['ranges'][key]
        if len(values)<2:assert result['low']==result['midpoint']==result['high']=='n.a.'
        else:
            assert math.isclose(cells[f'D{anchor}'],min(values),rel_tol=1e-10)
            assert math.isclose(cells[f'F{anchor}'],max(values),rel_tol=1e-10)
            assert all(result[name]==cells[f'{col}{output}'] for name,col in [('low','D'),('midpoint','E'),('high','F')])
            for name,multiple in [('low',min(values)),('midpoint',(min(values)+max(values))/2),('high',max(values))]:
                expected=(multiple*cells[f'AB{sr}'] if key=='pe' else multiple*cells[f'AA{sr}']-(cells[f'AC{sr}']-subject['values']['market_cap']/1e7))*1e7/shares
                assert math.isclose(result[name],expected,rel_tol=1e-10)
    if payload['company_id']=='itc':assert not selected and payload['source_reviews']


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
            check_valuation_peers(payload,workbook)
            findings=client.get(f"/analysis-reports/{entry['report_id']}/findings").raise_for_status().json()
            assert findings['company_id']==entry['company'] and findings['report_id']==entry['report_id']
            assert len(findings['sector_comparison']['rows'])==len(expected)
            assert findings['peer_valuation']==payload['peer_valuation']
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
    args.audit.write_text(json.dumps(data,indent=2),encoding='utf-8')


if __name__=='__main__':main()
