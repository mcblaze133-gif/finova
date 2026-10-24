"""Independent read-back checks of Excel outputs, not production valuations."""
import json
import math
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from backend import storage, results, evidence_packs

NS=results.NS

def cells(archive,strings,target):
    values={}
    root=ET.fromstring(archive.read(target))
    for cell in root.findall('.//s:sheetData/s:row/s:c',NS):
        assert cell.get('t')!='e',(target,cell.get('r'),'saved spreadsheet error')
        value=cell.findtext('s:v',namespaces=NS)
        if cell.get('t')=='s':value=strings[int(value)]
        elif cell.get('t')=='inlineStr':value=''.join(cell.find('s:is',NS).itertext())
        elif value is not None:
            try:value=float(value)
            except ValueError:pass
        values[cell.get('r')]=value
    return values

def equal(a,b,label):
    assert isinstance(a,(int,float)) and math.isclose(a,b,rel_tol=1e-10,abs_tol=.02),(label,a,b)

def main():
    checked=[]
    for company in ('britannia','hul','nestle-india','itc','tata-consumer'):
        row=storage.rows('SELECT * FROM excel_exports WHERE company=? AND status=? ORDER BY created_at DESC LIMIT 1',(company,'exported'))[0]
        path=Path(row['workbook_path']);data=json.loads(row['input_json'])
        with ZipFile(path) as archive:
            strings=[''.join(si.itertext()) for si in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si',NS)]
            book=ET.fromstring(archive.read('xl/workbook.xml'))
            rels={r.get('Id'):r.get('Target') for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
            sheets={}
            table_count=0
            for sheet in book.findall('s:sheets/s:sheet',NS):
                target=rels[sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
                target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
                sheets[sheet.get('name')]=cells(archive,strings,target)
                table_count+=sum(f.get('t')=='dataTable' for f in ET.fromstring(archive.read(target)).findall('.//s:f',NS))
            expected_sheets=19-sum(not data.get(k) for k in ('peers','transactions','assets','segments'))+int(len(data.get('sector_comparison',{}).get('rows',[]))>1)+int(bool(data.get('peer_valuation')))
            assert len(sheets)==expected_sheets and table_count==3
            assert 'Statement history' in sheets
            if data.get('sector_comparison',{}).get('rows'):
                peer_cells=sheets['Sector comparison']
                for i,peer in enumerate(data['sector_comparison']['rows'],6):
                    v=peer['values'];revenue=v['revenue']
                    assert peer_cells[f'C{i}']==peer['company']
                    for column,numerator,denominator in [('F','ebitda','revenue'),('G','cfo','net_income'),('H','capex','revenue')]:
                        if numerator in v and denominator in v and v[denominator]>0:equal(peer_cells[f'{column}{i}'],v[numerator]/v[denominator],peer['company']+' '+column)
                        else:assert peer_cells[f'{column}{i}']=='n.a.'
                    if 'prior_revenue' in v and v['prior_revenue']>0:equal(peer_cells[f'E{i}'],revenue/v['prior_revenue']-1,'peer matched growth')
                    else:assert peer_cells[f'E{i}']=='n.a.'
                    if 'debt' in v and 'cash' in v and revenue>0:equal(peer_cells[f'I{i}'],(v['debt']-v['cash'])/revenue,'peer net debt')
            history=sheets['Statement history']
            for y,period in enumerate(data['historical_statements']['periods']):
                c=chr(68+y)
                equal(history[f'{c}8'],period['duration_days'],'reporting period days')
                for i,metric in enumerate(data['historical_statements']['metrics']):
                    value=period['values'].get(metric['id'])
                    if value is not None:equal(history[f'{c}{10+i}'],value if metric['id']=='shares' else value/10000000,'historical statement readback')
            market=sheets['Market'];dashboard=sheets['Dashboard']
            equal(market['D25'],market['D10']+market['D13']-market['D9']-market['D11']-market['D12']-market.get('D29',0),'equity bridge claims once')
            for name,dest in [('Bear','D'),('Base','E'),('Bull','F')]:
                s=sheets[name]
                equal(s['E12'],s['E10']-s['E11'],name+' EBIT')
                equal(s['E18'],s['E14']+s['E11']-s['E15']-s['E17'],name+' FCFF')
                equal(s['E61'],market['D25']+s['E86'],name+' interim bridge')
                total=0
                displayed=[m for m in data['methods'] if m['applicable']!='No' or m['weight']]
                for i,method in enumerate(displayed):
                    if method['weight']:
                        total+=dashboard[f'{dest}{9+i}']*method['weight']
                equal(dashboard[f'{dest}25'],total,name+' method weights')
            if company=='itc':
                s=sheets['Segments']
                for model,col,g,m in [('Bear','K','E','H'),('Base','L','F','I'),('Bull','M','G','J')]:
                    total=sum(s[f'D{r}']*(1+s[f'{g}{r}'])*s[f'{m}{r}'] for r in range(6,11))
                    equal(s[f'{col}28'],total-s[f'{col}26']+sheets[model]['E61'],model+' SOTP')
                    equal(sheets[model]['G79'],s[f'{col}28']/market['D20'],model+' SOTP shares')
        checked.append({'company':company,'export_id':row['id'],'path':str(path),'sheets':len(sheets),'native_sensitivity_tables':table_count,
            'saved_formula_errors':0,'independent_bridge_and_forecast_checks':'passed','weighted_range':results.saved_valuation(company)['weighted'],
            'sha256':evidence_packs.digest_file(path),'native_desktop_excel_verified':False})
    out=storage.PROJECT_DIR/'reports/completed-model-verification.json'
    out.write_text(json.dumps({'checked_at':storage.now(),'companies':checked},indent=2),encoding='utf-8')
    print(json.dumps(checked,indent=2))

if __name__=='__main__':main()
