"""Read-back verification of the actual delivered workbook cells and links."""
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from datetime import date
from backend import storage,results,financial_history
from tools.verify_completed_models import cells,equal

def main():
    audit=[]
    for company in ('britannia','hul','itc','nestle-india','tata-consumer'):
        row=storage.rows("SELECT * FROM excel_exports WHERE company=? AND status='exported' ORDER BY created_at DESC LIMIT 1",(company,))[0]
        data=json.loads(row['input_json']);history=financial_history.build(company)
        assert data['historical_statements']==history,(company,'export differs from current reviewed records')
        with ZipFile(row['workbook_path']) as z:
            strings=[''.join(si.itertext()) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',results.NS)]
            rels={r.get('Id'):r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
            sheets={}
            for s in ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',results.NS):
                target=rels[s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
                target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
                sheets[s.get('name')]=cells(z,strings,target)
            h=sheets['Statement history'];reviewed=0
            for i,p in enumerate(history['periods']):
                c=chr(68+i)
                assert h[c+'5']==p['label'] and h[c+'7']==p['scope']
                equal(h[c+'8'],p['duration_days'],'period length')
                for j,m in enumerate(history['metrics']):
                    actual=h[f'{c}{10+j}'];v=p['values'].get(m['id'])
                    if v is None:assert actual=='n.a.',(company,p['end'],m['id'],'missing shown as number')
                    else:
                        equal(actual,v if m['id']=='shares' else v/10000000,(company,p['end'],m['id']))
                        assert p['sources'][m['id']][0]['url'];reviewed+=1
                if 'cfo' in p['values'] and 'capex' in p['values']:
                    equal(h[c+'31'],(p['values']['cfo']-p['values']['capex'])/10000000,'cash after capex')
                prev=history['periods'][i-1] if i else None
                comparable=prev and p['scope']==prev['scope'] and abs(p['duration_days']-prev['duration_days'])<=2 and 360<=(date.fromisoformat(p['end'])-date.fromisoformat(prev['end'])).days<=370
                if comparable:equal(h[c+'32'],p['values']['revenue']/prev['values']['revenue']-1,'matched revenue growth')
                else:assert h[c+'32']=='Not comparable'
            active=[m for m in data['methods'] if m['applicable']!='No' or m['weight']]
            for i,m in enumerate(active):assert str(sheets['Dashboard'][f'C{9+i}']).startswith(m['method'])
            for i in range(9+len(active),23):assert sheets['Dashboard'].get(f'C{i}') in ('',None)
            for sheet,key in [('Peers','peers'),('Transactions','transactions'),('NAV','assets'),('Segments','segments')]:
                assert (sheet in sheets)==bool(data.get(key)),(company,sheet,'unused tab not omitted')
        audit.append(dict(company=company,export_id=row['id'],checked_values=reviewed,periods=len(history['periods']),sheets=len(sheets),scope_and_duration_checks='passed',empty_modules_removed=True))
    (storage.PROJECT_DIR/'reports/statement-workbook-verification.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(audit,indent=2))

if __name__=='__main__':main()
