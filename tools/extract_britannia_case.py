"""Case-specific reviewed table mapping; no valuation arithmetic outside Excel."""
import hashlib
import json
import re
from decimal import Decimal as D
from pathlib import Path
from backend import storage, library
from backend.valuation_spec import FinancialRecord

BASE = storage.PROJECT_DIR / 'outputs/britannia-source-review'
SPECS = [('f8a1ed521b658b24',2023,114,115,'2023-05-05'),
         ('2d57301f8f927f01',2024,117,118,'2024-05-03'),
         ('73315d210bc45970',2025,132,133,'2025-05-08'),
         ('83b4e4ac30664191',2026,132,133,'2026-05-07')]

def pair(text, pattern, index=0):
    text='\n'.join(' '.join(line.split()) for line in text.splitlines())
    matches = list(re.finditer(pattern + r'[^\n]*?(\(?[\d,]+\.\d+\)?)\s+(\(?[\d,]+\.\d+\)?)\s*(?:\n|$)',text,re.I))
    if not matches:
        raise ValueError('Unmatched table row: '+pattern)
    match = matches[index]
    nums=[D(s.replace(',','').replace('(','-').replace(')','')) for s in match.groups()[-2:]]
    return nums,match.group(0).strip()

def main():
    storage.initialize()
    rows = {}
    audit = []
    for key,year,page,cashpage,pubdate in SPECS:
        doc=json.loads((BASE/(key+'.json')).read_text(encoding='utf-8'))
        text=doc['pages'][page-1]['text']; bs,pl=text.split('I Revenue from operations',1)
        cf=doc['pages'][cashpage-1]['text']
        pairs={}; proofs={}
        def take(metric,txt,pattern,index=0):
            pairs[metric],proofs[metric]=pair(txt,pattern,index)
        for metric,pattern in [('sales','Sale of goods'),('operating_other','Other operating revenues'),('other_income','II Other income'),
                               ('expenses','Total expenses'),('interest','Finance costs'),('da','Depreciation and amortisation expense'),
                               ('net_income','Owners of the Company')]:
            take(metric,pl,pattern)
        for metric,pattern,index in [('assets','Total assets',0),('liabilities','Total liabilities',0),
                    ('book_equity','Equity attributable to equity holders of the parent',0),('nci','Non-controlling interests',0),
                    ('cash','Cash and cash equivalents',0),('borrowings_long','Borrowings',0),('borrowings_short','Borrowings',1),
                    ('lease_long','Lease [Ll]iabilities',0),('lease_short','Lease [Ll]iabilities',1),
                    ('inventories','Inventories',0),('receivables','Trade receivables',0),
                    ('payables_small','total outstanding dues of micro enterprises and small enterprises',0),
                    ('payables_other','total outstanding dues of creditors other than micro enterprises and small enterprises',0)]:
            take(metric,bs,pattern,index)
        take('cfo',cf,'Net cash generated from operating activities')
        # The acquisition label wraps onto a second line in the source.
        flat=re.sub(r'Acquisition of property[\s\S]{0,180}?intangible\s+assets\s*', 'Cash capex ', cf, flags=re.I)
        take('capex_outflow',flat,'Cash capex')
        for offset,fy in [(1,year-1),(0,year)]:
            # Later reports' comparative columns supersede earlier presentations.
            v={k:vals[offset] for k,vals in pairs.items()}
            metrics={k:v[k] for k in ['assets','liabilities','book_equity','nci','cash','interest','da','net_income','cfo']}
            metrics.update(revenue=v['sales']+v['operating_other'],
                ebit=v['sales']+v['operating_other']-v['expenses']+v['interest'],
                ebitda=v['sales']+v['operating_other']-v['expenses']+v['interest']+v['da'],
                debt=v['borrowings_long']+v['borrowings_short']+v['lease_long']+v['lease_short'],
                operating_nwc=v['inventories']+v['receivables']-v['payables_small']-v['payables_other'],
                capex=abs(v['capex_outflow']),shares=D('240868296'))
            assert abs(metrics['assets']-metrics['liabilities']-metrics['book_equity']-metrics['nci'])<=D('.02')
            assert abs(metrics['ebitda']-metrics['da']-metrics['ebit'])<D('.01')
            for metric,value in metrics.items():
                stock=metric in ('assets','liabilities','book_equity','nci','cash','debt','operating_nwc','shares')
                evidence='\n'.join(proofs.values())
                description={'ebit':'Operating EBIT excluding other income and equity-accounted associate/JV results',
                    'ebitda':'Operating EBITDA = revenue from operations - total expenses + finance costs + D&A',
                    'debt':'Borrowings plus lease liabilities, current and non-current',
                    'operating_nwc':'Core trade NWC = inventories + trade receivables - trade payables; other operating balances excluded',
                    'capex':'Cash purchase of PPE, CWIP and intangibles, gross of disposal proceeds',
                    'shares':'Exact diluted weighted-average share count; unchanged in all five annual statements',
                    'da':'Depreciation and amortisation expense'}.get(metric,metric.replace('_',' '))
                record=FinancialRecord(company='britannia',metric=metric,value=str(value),
                    unit='shares' if metric=='shares' else 'INR_crore',period_start=None if stock else f'{fy-1}-04-01',
                    period_end=f'{fy}-03-31',accounting_scope='consolidated',operations_scope='total',
                    definition=description,source_type='historical',source_url=(library.root_folder()/doc['file']).as_uri(),
                    source_file=doc['file'],source_page=str(cashpage if metric in ('cfo','capex') else page),source_date=pubdate,
                    review_status='source_verified',source_sha256=doc['sha256'],source_quote=evidence,
                    review_note='SignalAI source review: exact consolidated table row mapping, annual period/unit checks and balance/earnings reconciliation. FY2026 statements and tax note visually checked. Not a claim of user verification.')
                rows[(fy,metric)]=record
            audit.append({'year':fy,'report_year':year,'values_crore':{k:str(x) for k,x in metrics.items()},'page':page,'cash_page':cashpage})
    records=[r for (year,_),r in rows.items() if year>=2022]
    (BASE/'reviewed-financial-records.json').write_text(json.dumps([r.model_dump(mode='json') for r in records],indent=2),encoding='utf-8')
    (BASE/'extraction-audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    with storage.database() as db:
        for r in records:
            payload=r.model_dump_json();rid=hashlib.sha256(payload.encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO library_records VALUES(?,?,?,?,?)',(rid,r.company,payload,r.source_sha256,storage.now()))
    print(json.dumps({'reviewed_records':len(records),'years':list(range(2022,2027)),'latest':audit[-1]},indent=2))

if __name__=='__main__':
    main()
