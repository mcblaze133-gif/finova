"""Curate source-reported results; no forecast or valuation arithmetic."""
import json
import re
from backend import storage, library, evidence_packs

CASES = {
 'hul': {
  'file':'HUL/analyst report/hul-jq-26-results-presentation.pdf', 'page':2,
  'period':'Quarter ended 30 June 2026', 'scope':'Consolidated',
  'metrics':[
   ('Turnover','₹17,184 crore','17,184'),('EBITDA','₹3,947 crore','3,947'),
   ('Reported profit after tax','₹2,680 crore','2,680'),('Underlying volume growth','5%','Underlying Volume Growth 5%')],
  'finding':('Reported profit and underlying performance differ',
    'The supplied release reports a 2% decline in profit after tax, but 9% growth in profit before exceptional items. It attributes the reported decline to a prior-year one-off tax credit.',
    'A lower reported profit does not, by itself, establish deteriorating operations. Compare the recurring earnings basis before applying a P/E multiple.'),
  'summary':'The supplied June-quarter release reports volume-led growth alongside a weaker reported profit comparison affected by a prior-year tax credit. A company valuation has not yet been completed.'
 },
 'itc': {
  'file':'ITC/report/ITC-Report-and-Accounts-2026.pdf', 'page':253,
  'period':'Year ended 31 March 2026', 'scope':'Consolidated; continuing operations where specified',
  'metrics':[
   ('Revenue from operations, including excise','₹89,913.33 crore','89913.33'),
   ('Profit from continuing operations','₹21,018.15 crore','21018.15'),
   ('Parent-attributable profit, total','₹20,689.47 crore','20689.47'),
   ('Diluted EPS, continuing operations','₹16.51','16.51')],
  'finding':('Discontinued operations distort the profit comparison',
    'The supplied annual statement reports FY2025 profit from discontinued operations of ₹15,016.01 crore. FY2026 shows none. Continuing-operations profit is ₹21,018.15 crore against ₹20,036.47 crore in FY2025.',
    'A comparison of total profit across these years mixes different business scopes. Reconcile continuing earnings and segment economics before selecting valuation multiples.'),
  'summary':'The supplied annual filing shows why total profit and continuing-business profit must be analysed separately. ITC also needs segment-sensitive valuation treatment; a completed company valuation is not available yet.'
 },
 'nestle-india': {
  'file':'nestle/reports/Nestle India_AR FY 2025-26.pdf', 'page':118,
  'period':'Year ended 31 March 2026', 'scope':'Consolidated; amounts in INR million as reported',
  'metrics':[
   ('Revenue from operations','₹231,546.0 million','231,546.0'),
   ('Reported EBITDA','₹53,060.6 million','53,060.6'),
   ('Profit for the year','₹34,990.8 million','34,990.8'),
   ('Basic and diluted EPS','₹18.15','18.15')],
  'finding':('Use operating earnings and attributable profit consistently',
    'The supplied annual statement reports EBITDA of ₹53,060.6 million and profit for the year of ₹34,990.8 million. Its EBITDA definition and associate results are shown separately in the statement.',
    'Use the disclosed EBITDA definition consistently across peers. An earnings multiple and an enterprise-value multiple require different earnings and balance-sheet bridges.'),
  'summary':'Selected annual financial results are available from the supplied consolidated statement. Peer normalisation, valuation assumptions and the company-specific Excel model are still incomplete.'
 },
 'tata-consumer': {
  'file':'tata consumer/analyst presentation/Q1FY27 Investor Presentation FINAL.pdf', 'page':5,
  'period':'Quarter ended 30 June 2026', 'scope':'Consolidated presentation; individual business metrics labelled',
  'metrics':[
   ('Consolidated revenue growth','12%','Consolidated revenue grew 12%'),
   ('Consolidated EBITDA growth','19%','Consolidated EBITDA grew 19%'),
   ('Consolidated EBITDA margin','13.6%','13.6%'),
   ('India business volume growth','13%','13% underlying volume growth')],
  'finding':('Tea revenue decline is not the same as volume decline',
    'The supplied presentation reports India tea volume growth of 2% and a revenue decline of 4%, attributing the difference to passing lower tea costs to consumers. Growth businesses grew 47% and reached 36% of the India business.',
    'Separate pricing pass-through, volumes and business mix before forecasting growth or margins. Applying one growth assumption across all businesses would conceal these differences.'),
  'summary':'The supplied June-quarter presentation reports volume growth and stronger EBITDA, while tea pricing pass-through reduces tea revenue. A completed valuation still requires validated financial schedules and company-specific assumptions.'
 }
}


def main():
    for company, case in CASES.items():
        row = storage.rows('SELECT d.id,d.sha256,p.text FROM library_documents l JOIN documents d ON l.document_id=d.id JOIN passages p ON p.document_id=d.id WHERE l.company=? AND l.relative_path=? AND p.pdf_page=?',
                           (company,case['file'],case['page']))[0]
        assert evidence_packs.digest_file(library.root_folder()/case['file']) == row['sha256']
        text = ' '.join(row['text'].split())
        for label, display, proof in case['metrics']:
            assert proof in text, (company,label,'Not present in supplied source')
        title, finding, use = case['finding']
        data = {'investor_summary':case['summary'], 'findings':[{'title':title,'finding':finding,'investor_use':use}],
                'reported_results':{'period':case['period'],'scope':case['scope'],
                    'metrics':[{'label':a,'display_value':b,'source_value':c} for a,b,c in case['metrics']],
                    'source_file':case['file'],'source_sha256':row['sha256'], 'source_page':case['page'],
                    'source_document_id':row['id'], 'source_quote':text,
                    'qualification':'Source-reported figures from the supplied document. These are not valuation estimates or independently corroborated financials.'}}
        path = storage.PROJECT_DIR/'config/company_briefs'/f'{company}.json'
        path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
        print(company+': source-reported results prepared')


if __name__ == '__main__':
    main()
