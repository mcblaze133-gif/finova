"""Reviewed source-row mapping for FY25/FY26, without valuation calculations.

All amounts below are source facts in the stated original units. Arithmetic is
restricted to reconciling statement definitions and normalising input units.
"""
import hashlib
import json
from decimal import Decimal as D
from backend import storage, library
from backend.valuation_spec import FinancialRecord


SPECS = {
 'hul':dict(doc=8,bs=10,pl=8,cf=None,shares_page=(199,398),date='2026-04-30',unit='INR_crore',scope='continuing',
   facts={
    'revenue':['64468','61328'],'ebitda':['15054','14706'],'da':['1333','1253'],
    'net_income':['10633','10658'],'interest':['410','381'],
    'assets':['79752','79880'],'liabilities':['30744','30271'],'book_equity':['48739','49402'],
    'nci':['269','207'],'cash':['2583','6071'],'debt':['1478','1648'],
    'operating_nwc':['-5157','-3081'],'nonoperating_assets':['4622','5174'],
    'shares':['2349591262','2349591262'],'preferred':['0','0']},
   definitions={
    'ebitda':'Continuing operating EBITDA as disclosed, excluding other income, exceptional items and joint-venture results.',
    'net_income':'Attributable continuing PAT, excluding ice-cream demerger and discontinued operations; annual report PDF419.',
    'debt':'Current and non-current lease liabilities plus borrowings. Other contractual acquisition liabilities are a separate unresolved claim.',
    'operating_nwc':'Core trade NWC: inventories + trade receivables - both trade-payable categories. FY25 includes pre-demerger balance scope; no historical growth extrapolation.',
    'nonoperating_assets':'Carrying-value proxy: current/non-current investments, loans, equity-method investment and unrestricted term deposits128/1231cr. Excludes earmarked bank balances537/252cr. Not a fair-value appraisal.'}),
 'itc':dict(doc=195,bs=252,pl=253,cf=256,shares_page=(195,291),date='2026-05-21',unit='INR_crore',scope='continuing',
   facts={
    'revenue':['78868.40','75323.34'],'ebitda':['27317.91','25978.21'],'da':['1710.53','1646.32'],
    'net_income':['20689.47',None],'interest':['85.17','45.06'],
    'assets':['93792.38','88090.68'],'liabilities':['20919.36','17692.74'],'book_equity':['72507.30','70030.05'],
    'nci':['365.72','367.89'],'cash':['643.46','620.00'],'debt':['2399.06','284.54'],
    'operating_nwc':['17155.96','15748.51'],'nonoperating_assets':['40541.85','38186.85'],
    'shares':['12529468231','12514119781'],'preferred':['0','0'],
    'cfo':['18464.31',None],'capex':['2182.89',None]},
   definitions={
    'revenue':'Revenue from operations net of excise duty: 89913.33-11044.93 (FY26), 81612.78-6289.44 (FY25). Excise is removed from expenses as well when deriving operating profit.',
    'ebitda':'Operating EBITDA: gross revenue - total expenses + finance cost + D&A. Other income, associates, exceptional items and hotel demerger gain excluded.',
    'net_income':'FY26 parent continuing PAT. FY25 parent continuing split left unavailable rather than using total PAT inflated by hotel demerger.',
    'operating_nwc':'Inventories + biological assets + trade receivables - both trade-payable categories.',
    'debt':'Current/noncurrent borrowings and lease liabilities.',
    'nonoperating_assets':'Carrying proxy: investments12089.55+20750.64, equity-method5288.24, investment property303.36, unrestricted deposits2096.67 and loans4.87+8.52. Earmarked bank268.66 excluded; add once.'}),
 'nestle-india':dict(doc=136,bs=117,pl=118,cf=119,shares_page=(136,134),date='2026-04-21',unit='INR',scope='total',factor='1000000',
   facts={
    'revenue':['231546.0','202015.6'],'ebitda':['53060.6','47695.8'],'da':['6992.3','5399.2'],
    'net_income':['34990.8','32075.9'],'interest':['1583.1','1360.0'],
    'assets':['131824.9','121933.2'],'liabilities':['80255.2','81831.1'],'book_equity':['51569.7','40102.1'],
    'nci':['0','0'],'cash':['13205.7','761.8'],'debt':['4441.6','11668.5'],
    'operating_nwc':['-679.6','8397.6'],'nonoperating_assets':['5509.9','5934.3'],
    'shares':['1928314320','964157160'],'preferred':['0','0'],
    'cfo':['50475.6','29345.3'],'capex':['8297.0','20086.4'],'dividends':['23139.8','24586.0']},
   definitions={
    'shares':'Exact closing shares. FY26 includes 1:1 bonus on 11-Aug-2025; FY25 closing shares unadjusted. Historical EPS comparisons require bonus-adjusted denominators.',
    'debt':'Deferred VAT borrowings plus current/noncurrent lease liabilities and bank borrowing.',
    'operating_nwc':'Inventory + trade receivables - operating trade payables. Capex payables excluded.',
    'nonoperating_assets':'Associate carrying value plus employee loans. Restricted unpaid-dividend bank balances excluded.',
    'ebitda':'Company disclosed EBITDA excludes other income, exceptional items and associate results.'}),
 'tata-consumer':dict(doc=198,bs=12,pl=13,cf=15,shares_page=(198,44),date='2026-05-08',unit='INR_crore',scope='total',
   facts={
    'revenue':['20290.43','17618.30'],'ebitda':['2791.80','2479.35'],'da':['626.68','600.74'],
    'net_income':['1542.30','1278.47'],'interest':['137.03','290.20'],
    'assets':['34452.96','31977.68'],'liabilities':['11264.10','10587.38'],'book_equity':['21787.53','20001.08'],
    'nci':['1401.33','1389.22'],'cash':['3046.57','2725.93'],'debt':['2819.51','2392.68'],
    'operating_nwc':['799.79','961.27'],'nonoperating_assets':['2842.60','1740.12'],
    'shares':['989561780','989498558'],'preferred':['0','0'],
    'cfo':['2421.85','2056.65'],'capex':['448.57','459.54'],'dividends':['816.34','738.45']},
   definitions={
    'ebitda':'Operating EBITDA excludes other income, exceptional items and equity-method associate/JV results.',
    'debt':'Borrowings (including cash-management overdrafts) plus lease liabilities. Balance-sheet cash used gross, not cash-flow cash net of overdrafts, to avoid double subtraction.',
    'operating_nwc':'Inventories + trade receivables - trade payables.',
    'nonoperating_assets':'Carrying proxy: equity-method investments, financial investments, loans, unrestricted bank deposits349.94/70.82 and investment property under development. Unclaimed dividends23.98/21.11 excluded. No brand/goodwill addition.',
    'dividends':'Parent dividends paid, not proposed FY26 final dividend; PDF45. Forecast cash payment timing remains an assumption.'})
}


def main():
    audit=[]
    for company,spec in SPECS.items():
        doc=storage.rows('SELECT d.*,l.relative_path FROM documents d JOIN library_documents l ON l.document_id=d.id WHERE d.id=? LIMIT 1',(spec['doc'],))[0]
        path=library.root_folder()/doc['relative_path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==doc['sha256']
        def evidence(d,p):
            return storage.rows('SELECT text FROM passages WHERE document_id=? AND pdf_page=?',(d,p))[0]['text']
        for i,fy in enumerate((2026,2025)):
            facts={k:D(v[i]) for k,v in spec['facts'].items() if v[i] is not None}
            facts['ebit']=facts['ebitda']-facts['da']
            assert abs(facts['assets']-facts['liabilities']-facts['book_equity']-facts['nci'])<D('.02')
            for metric,value in facts.items():
                stock=metric in ('assets','liabilities','book_equity','nci','cash','debt','operating_nwc','shares','preferred','nonoperating_assets')
                page=spec['cf'] if metric in ('cfo','capex','dividends') else spec['bs'] if stock else spec['pl']
                d=spec['doc']
                if metric=='shares':d,page=spec['shares_page']
                if company=='hul' and metric=='net_income':d,page=199,419
                if company=='hul' and metric=='nonoperating_assets':d,page=199,364
                if company=='tata-consumer' and metric=='dividends':page=45
                # Derived input rows cite the same source statements used in their
                # definition. This is preparation of facts, not model valuation.
                quote='\n'.join(' '.join(line.split()) for line in evidence(d,page).splitlines())
                source_pages=str(page)
                extra={('hul','nonoperating_assets'):[397],('itc','nonoperating_assets'):[290],('tata-consumer','nonoperating_assets'):[43]}.get((company,metric),[])
                for note_page in extra:
                    quote+='\nAdditional source page '+str(note_page)+':\n'+'\n'.join(' '.join(line.split()) for line in evidence(d,note_page).splitlines())
                    source_pages+=','+str(note_page)
                sourcedoc=storage.rows('SELECT d.*,l.relative_path FROM documents d JOIN library_documents l ON l.document_id=d.id WHERE d.id=? LIMIT 1',(d,))[0]
                record=FinancialRecord(company=company,metric=metric,value=str(value if metric=='shares' else value*D(spec.get('factor','1'))),
                    unit='shares' if metric=='shares' else spec['unit'],period_start=None if stock else f'{fy-1}-04-01',period_end=f'{fy}-03-31',
                    accounting_scope='consolidated',operations_scope=spec['scope'],definition=spec.get('definitions',{}).get(metric,metric.replace('_',' ')+' on the stated consolidated reporting basis'),
                    source_type='historical',source_url=(library.root_folder()/sourcedoc['relative_path']).as_uri(),source_file=sourcedoc['relative_path'],source_page=source_pages,
                    source_date=spec['date'],review_status='source_verified',source_sha256=sourcedoc['sha256'],source_quote=quote[:7900],
                    review_note='Exact statement row review and balance-sheet reconciliation. Derived definitions are explicit. Historical FY25 comparability qualifications remain in the case notes. No user-verification claim.')
                payload=record.model_dump_json();rid=hashlib.sha256(payload.encode()).hexdigest()
                with storage.database() as db:
                    # Replace only records written by this reviewed mapping,
                    # never unrelated imported facts or manual analyst edits.
                    db.execute("DELETE FROM library_records WHERE company=? AND json_extract(record_json,'$.metric')=? AND json_extract(record_json,'$.period_end')=? AND json_extract(record_json,'$.review_note') LIKE 'Exact statement row review and balance-sheet reconciliation.%'",(company,metric,f'{fy}-03-31'))
                    db.execute('INSERT OR IGNORE INTO library_records VALUES(?,?,?,?,?)',(rid,company,payload,sourcedoc['sha256'],storage.now()))
            audit.append({'company':company,'year':fy,'facts_original_units':{k:str(v) for k,v in facts.items()},'source_document':spec['doc']})
    target=storage.PROJECT_DIR/'reports/remaining-financial-source-review.json'
    target.write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print('Stored reviewed financial inputs for four companies, with explicit source definitions and reconciliations.')


if __name__=='__main__':main()
