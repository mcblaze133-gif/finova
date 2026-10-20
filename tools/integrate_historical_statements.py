"""Explicitly reviewed annual statement rows; no estimates and no AI calls.

Image-only Tata/HUL tables were read from rendered original PDF pages. Values
retain the original reporting period and scope; they are not restated estimates.
"""
import hashlib
import json
from decimal import Decimal as D
from backend import storage, library
from backend.valuation_spec import FinancialRecord

ROWS = []
def add(company, doc, year, pl, bs, cf, values, *, start=None, accounting='consolidated', factor=1, note=''):
    ROWS.append(dict(company=company,doc=doc,year=year,pl=pl,bs=bs,cf=cf,values=values,
                     start=start or f'{year-1}-04-01',accounting=accounting,factor=factor,note=note))

add('hul',68,2022,15,17,18,dict(revenue=52446,net_income=8879,da=1091,interest=106,
    assets=70517,liabilities=21430,book_equity=49061,nci=26,cash=1147,cfo=9048,capex=1228,dividends=7526),
    note='Pre ice-cream demerger reporting perimeter. Revenue sums product, service and other operating revenue. D&A is P&L D&A, not the different cash-flow adjustment. Capex = PPE1225 + intangibles3. Parent PAT includes discontinued operations.')
add('hul',69,2023,16,18,19,dict(revenue=60580,net_income=10120,da=1137,interest=114,
    assets=73087,liabilities=22565,book_equity=50304,nci=218,cash=714,cfo=9991,capex=1192,dividends=8474),
    note='Pre ice-cream demerger perimeter. Capex = PPE1174 + intangibles18. Parent PAT includes discontinued operations. Original FY23 P&L is used; FY24 comparative restates some expense rows by 1 crore.')
add('hul',73,2024,9,11,12,dict(revenue=61896,net_income=10277,da=1216,interest=334,
    assets=78499,liabilities=27076,book_equity=51218,nci=205,cash=825,cfo=15469,capex=1477,dividends=9416),
    note='Pre ice-cream demerger perimeter. Capex = PPE1468 + intangibles9. Not restated to FY26 continuing operations.')

for year,doc,bs,pl,cf,vals in [
 (2022,111,268,269,272,['65204.96','4536.87','46318.32','39.36','1732.41','15242.66','77259.55','62455.57','366.30','271.37','15775.51','2141.64']),
 (2023,112,272,273,276,['76518.21','5581.36','52705.49','43.20','1809.01','19191.66','85882.98','69155.26','383.53','463.35','18877.55','2742.99']),
 (2024,113,286,287,290,['76840.49','5959.49','52448.49','45.96','1816.39','20458.78','91826.16','74507.00','382.97','625.89','17178.86','3562.53'])]:
    gross,excise,expense,interest,da,pat,assets,book,nci,cash,cfo,capex=map(D,vals)
    add('itc',doc,year,pl,bs,cf,dict(revenue=gross-excise,ebitda=gross-expense+interest+da,
        da=da,ebit=gross-expense+interest,interest=interest,net_income=pat,assets=assets,
        book_equity=book,nci=nci,liabilities=assets-book-nci,cash=cash,cfo=cfo,capex=capex),
        note='Includes hotels before demerger; not restated to FY26 continuing operations. Revenue is gross revenue less excise; EBITDA = gross revenue - total expenses + finance cost + D&A, excluding other income. Liabilities = assets - parent equity - NCI.')

add('nestle-india',135,2022,54,52,56,dict(revenue='168969.6',net_income='23905.2',da='4030.1',interest='1545.7',
    assets='89787.4',liabilities='65195.7',book_equity='24591.7',cash='9265.5',cfo='27374.3',capex='5499.2',dividends='20247.3'),
    start='2022-01-01',accounting='standalone',factor=1000000,
    note='Calendar year ended 31-Dec-2022. Original INR million converted once to INR. No synthetic FY2023. Standalone, not consolidated. Closing balance sheet spans PDF52-53; P&L54-55; cash flow56-57.')
add('nestle-india',196,2024,96,94,98,dict(revenue='243938.9',net_income='39328.4',da='5377.8',interest='1454.9',
    assets='105230.6',liabilities='71821.7',book_equity='33408.9',cash='7588.7',cfo='41747.9',capex='18826.7',dividends='30081.8'),
    start='2023-01-01',accounting='standalone',factor=1000000,
    note='15 months Jan2023-Mar2024, not annualised. Original INR million converted once to INR. Standalone. Balance sheet94-95; P&L96-97; cash flow98-99. Do not compare raw growth to a 12-month year.')

add('tata-consumer',171,2022,8,11,12,dict(revenue='12245.37',ebitda='1538.78',ebit='1260.77',net_income='935.78',da='278.01',interest='72.78',
    assets='21117.59',liabilities='4824.03',book_equity='15141.94',nci='1151.62',cash='1497.97',
    cfo='1515.81',capex='273.34',dividends='398.19',debt='1412.01',operating_nwc='1185.81'),
    note='FY22 comparative from FY23 audited statements. Debt = borrowings241.87+768.72 + leases350.91+50.51. Core trade NWC = inventory2266.51 + receivables835.15 - payables1915.85. Gross BS cash retained; CF nets overdraft.')
add('tata-consumer',171,2023,8,11,12,dict(revenue='13783.16',ebitda='1856.47',ebit='1552.39',net_income='1203.77',da='304.08',interest='87.16',
    assets='22811.13',liabilities='5684.25',book_equity='16276.71',nci='850.17',cash='1539.56',
    cfo='1461.29',capex='311.75',dividends='573.42',debt='1600.04',operating_nwc='1151.82'),
    note='Debt = borrowings206.12+976.70 + leases362.21+55.01. Core trade NWC = inventory2701.67 + receivables798.33 - payables2348.18. Gross BS cash retained; CF nets overdraft.')
add('tata-consumer',177,2024,8,11,12,dict(revenue='15205.85',ebitda='2284.10',ebit='1906.95',net_income='1150.33',da='377.15',interest='129.81',
    assets='28020.94',liabilities='10584.81',book_equity='16056.79',nci='1379.34',cash='2319.83',
    cfo='1936.68',capex='334.69',dividends='808.85',debt='3477.22',operating_nwc='958.95'),
    note='Acquisition/perimeter changes limit organic growth interpretation. Debt = borrowings168.35+2785.50 + leases459.55+63.82. Core trade NWC = inventory2769.35 + receivables896.75 - payables2707.15. Gross BS cash retained; CF nets overdraft.')

STOCKS={'assets','liabilities','book_equity','nci','cash','debt','operating_nwc'}
def main():
    audit=[]
    for row in ROWS:
        doc=storage.rows('SELECT d.*,l.relative_path FROM documents d JOIN library_documents l ON l.document_id=d.id WHERE d.id=? LIMIT 1',(row['doc'],))[0]
        path=library.root_folder()/doc['relative_path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==doc['sha256']
        values={k:D(str(v)) for k,v in row['values'].items()}
        if row['company']=='tata-consumer':
            expenses=D({2022:'11057.38',2023:'12317.93',2024:'13428.71'}[row['year']])
            assert values['ebitda']==values['revenue']-expenses+values['interest']+values['da']
            row['note']+=' EBITDA = revenue - total expenses + finance cost + D&A; excludes other income, exceptional items and associates/JVs. EBIT = EBITDA - D&A.'
        assert abs(values['assets']-values['liabilities']-values['book_equity']-values.get('nci',D(0)))<=D('.02'),row
        end=f"{row['year']}-03-31" if not (row['company']=='nestle-india' and row['year']==2022) else '2022-12-31'
        for metric,v in values.items():
            page=row['bs'] if metric in STOCKS else row['cf'] if metric in ('cfo','capex','dividends') else row['pl']
            pages=[page,page+1] if row['company']=='nestle-india' else [page]
            # A transcription is explicitly marked; it is not presented as OCR text.
            quote=f"Reviewed transcription: {metric} = {v}; original unit {'INR million' if row['factor']==1000000 else 'INR crore'}; period {row['start']} to {end}. {row['note']}"
            rec=FinancialRecord(company=row['company'],metric=metric,value=str(v*row['factor']),
                unit='INR' if row['factor']==1000000 else 'INR_crore',period_start=None if metric in STOCKS else row['start'],period_end=end,
                accounting_scope=row['accounting'],operations_scope='total',definition=metric.replace('_',' ')+'. '+row['note'],
                source_file=doc['relative_path'],source_page=','.join(map(str,pages)),source_url=path.as_uri(),source_date=end,
                source_type='historical',review_status='source_verified',source_sha256=doc['sha256'],source_quote=quote,
                review_note='Historical statement integration v1. Original PDF table manually reviewed, including image-only tables. Source date denotes period end; not a claimed publication date. '+row['note'])
            payload=rec.model_dump_json();rid=hashlib.sha256(payload.encode()).hexdigest()
            with storage.database() as db:
                db.execute("DELETE FROM library_records WHERE company=? AND json_extract(record_json,'$.metric')=? AND json_extract(record_json,'$.period_end')=? AND json_extract(record_json,'$.review_note') LIKE 'Historical statement integration v1.%'",(row['company'],metric,end))
                db.execute('INSERT OR IGNORE INTO library_records VALUES(?,?,?,?,?)',(rid,row['company'],payload,doc['sha256'],storage.now()))
        audit.append(dict(company=row['company'],period_start=row['start'],period_end=end,document_id=row['doc'],pages=[row['pl'],row['bs'],row['cf']],metrics=len(values),balance_reconciled=True,note=row['note']))
    (storage.PROJECT_DIR/'reports/historical-statement-integration.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(f'Integrated {sum(r["metrics"] for r in audit)} reviewed historical statement rows; {len(audit)} statement periods reconciled.')

if __name__=='__main__':main()
