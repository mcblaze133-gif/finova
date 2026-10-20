"""Explicit dated Britannia analyst case. These are estimates, not FMCG defaults."""
import hashlib
import json
from pathlib import Path
from backend import storage, library, assumptions
from backend.valuation_spec import Assumption, FinancialRecord, METHODS

def main():
    storage.initialize()
    from backend.companies import Company
    profile=Company(id='britannia',legal_name='Britannia Industries Limited',business_model='fmcg',domains=['britannia.co.in'],
        seeds=['https://www.britannia.co.in/investors/financial-performance/financial-results?tab=financial-performance'])
    with storage.database() as db:
        db.execute('INSERT OR REPLACE INTO companies(id,legal_name,business_model,profile_json) VALUES(?,?,?,?)',
                   (profile.id,profile.legal_name,profile.business_model,profile.model_dump_json()))
    root=storage.PROJECT_DIR
    doc=json.loads((root/'outputs/britannia-source-review/83b4e4ac30664191.json').read_text(encoding='utf-8'))
    supporting=[('preferred','0','Only ordinary share capital and other equity shown; no preferred capital in the consolidated balance sheet.',132),
       ('nonoperating_assets','3727.66','Carrying-value proxy: non-current investments 1517.71 + current investments 1638.52 + loans 90 + equity-accounted interests 453.53 + investment property 27.90. Not an independent fair-value assessment.',132),
       ('dividends','1803.95','FY2026 cash dividends paid; not the subsequent FY2026 dividend recommendation.',134)]
    with storage.database() as db:
        for metric,value,description,page in supporting:
            record=FinancialRecord(company='britannia',metric=metric,value=value,unit='INR_crore',
                period_start='2025-04-01' if metric=='dividends' else None,period_end='2026-03-31',
                accounting_scope='consolidated',operations_scope='total',definition=description,
                source_type='historical',source_url=(library.root_folder()/doc['file']).as_uri(),
                source_file=doc['file'],source_page=str(page),source_date='2026-05-07',review_status='source_verified',
                source_sha256=doc['sha256'],source_quote=doc['pages'][page-1]['text'][:7900],
                review_note='SignalAI source review; supporting balances and carrying amounts. Fair-value use remains an explicit valuation approximation.')
            payload=record.model_dump_json();rid=hashlib.sha256(payload.encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO library_records VALUES(?,?,?,?,?)',(rid,'britannia',payload,doc['sha256'],storage.now()))
    annual='Local FY2026 annual report: PDF pp132-134,144-146,154; annual FY2022-26 statement history'
    call='Local Q1 FY27 presentation pp16-19 and 7-Aug-2026 earnings call pp5-8,15; https://media.britannia.co.in/Britannia_Earnings_Aug07_2026_Updated_6288b5faf7.pdf'
    case_values={
      'volume_growth':[[.04]*5,[.07,.065,.06,.055,.05],[.09,.08,.07,.065,.06]],
      'price_mix_growth':[[.01,.015,.015,.02,.02],[.02,.02,.025,.025,.025],[.03]*5],
      'ebitda_margin':[[.17,.17,.172,.172,.175],[.18,.183,.186,.188,.19],[.188,.192,.196,.20,.205]],
      'da_ratio':[[.018]*5,[.018]*5,[.018]*5],
      'capex_ratio':[[.025]*5,[.02]*5,[.018]*5],
      'nwc_ratio':[[0]*5,[-.004]*5,[-.008]*5],
      'tax_rate':[[.2517]*5]*3,
      'risk_free_rate':[[.074]*5]*3,
      'beta':[[1]*5,[.85]*5,[.7]*5],
      'equity_risk_premium':[[.06]*5]*3,
      'pretax_cost_debt':[[.09]*5]*3,
      'debt_weight':[[.012]*5]*3,
      'terminal_growth':[[.035]*5,[.045]*5,[.055]*5],
      'terminal_roic':[[.25]*5,[.35]*5,[.45]*5],
      'terminal_roe':[[.25]*5,[.35]*5,[.45]*5],
      'net_borrowing':[[0]*5]*3,
      'interest_rate':[[.085]*5]*3,
      'nonoperating_income':[[1939400000]*5]*3,
      'nci_profit':[[35200000]*5]*3,
      'shares_change':[[0]*5]*3,
      'equity_proceeds':[[0]*5]*3,
      'other_equity_changes':[[0]*5]*3,
      'dividend_payout':[[.75]*5,[.8]*5,[.85]*5],
      'selected_pe':[[30]*5,[37.5]*5,[45]*5],
      'selected_ev_ebitda':[[20]*5,[25]*5,[30]*5],
      'terminal_value_limit':[[.75]*5]*3,
      'method_divergence_limit':[[.5]*5]*3,
    }
    explanations={
      'volume_growth':'Q1 FY27 management described 9% tonnage growth, GT recovery and faster adjacencies. Bear assumes material slowdown; base fades from 7% to 5%; bull starts at the disclosed quarter rate and fades. These are annual forecasts, not company guidance.',
      'price_mix_growth':'Q1 net sales grew 9.5% with 9% tonnage; management described partial price recovery against fuel and packaging inflation. Future 1-3% price/mix assumes gradual pass-through. Net-sales tonnage is a proxy for total operating revenue; subsidy revenue need not scale identically.',
      'ebitda_margin':'FY26 operating EBITDA is 18.51% of audited operating revenue. Q1 FY27 operating profit margin was 15.3% before D&A and management flagged fuel, laminates and brand spending. Base recovery is gradual; bear retains cost pressure; bull requires efficiencies and pricing.',
      'tax_rate':'Use the disclosed domestic 25.17% tax rate. Do not extrapolate FY26 22.66% effective tax or the INR82.10cr prior-year tax benefit.',
      'capex_ratio':'Cash capex fell from INR711.46cr in FY23 to INR205.57cr in FY26 after capacity expansion. Base 2% sales allows maintenance and growth; bear 2.5% reduces free cash flow. Bull 1.8% requires high capacity utilization. Terminal reinvestment is separately constrained by ROIC.',
      'da_ratio':'FY26 D&A / revenue is approximately 1.76%. Use 1.8% as a company-calibrated estimate; no fixed-asset vintage schedule is available.',
      'nwc_ratio':'FY26 inventories + receivables - trade payables equals negative INR81.27cr, about -0.42% of revenue. Base broadly holds that ratio; bear removes supplier-funded growth; bull requires better inventory/payable turns. Other operating balance changes are assumed neutral and need review.',
      'risk_free_rate':'7.4% is a rounded analyst nominal-INR rate proxy, not a verified same-day RBI/CCIL fixing. Current official yield validation is incomplete. Discount-rate scenarios must not be represented as a measured CAPM estimate.',
      'beta':'Analyst risk coefficient 1.00/0.85/0.70 reflects downside cyclicality versus branded staple stability. Not a regression beta. A measured return series is not in the supplied library.',
      'equity_risk_premium':'6% is an explicit analyst equity-risk assumption over the nominal INR bond-rate proxy. It is not a sourced current market premium; do not add a second country premium to this assumption.',
      'pretax_cost_debt':'9% is a financing stress estimate relative to FY26 finance cost and gross borrowings, not a verified refinancing quote.',
      'interest_rate':'8.5% of opening gross debt is an analyst interest-cost proxy, close to FY26 finance costs / closing gross debt. Average debt and future repricing can differ.',
      'debt_weight':'Approximately 1.2% gross debt / (spot market equity + gross debt); small capital-structure weight estimated using the dated INR4764 share-price reference.',
      'terminal_growth':'3.5%/4.5%/5.5% nominal perpetual growth are analyst scenarios after explicit growth fades. They require long-run reinvestment and are not management forecasts.',
      'terminal_roic':'25%/35%/45% terminal return assumptions reflect a branded, low-core-working-capital business but substantial fade versus recent core returns. They are judgments; terminal capex/reinvestment must step up from the explicit-period profile.',
      'terminal_roe':'Terminal ROE judgments shown for completeness. FCFE, DDM and residual income are excluded from reconciliation in this run.',
      'selected_pe':'30x/37.5x/45x are analyst multiple stress cases, referenced to roughly 45x spot FY26 reported earnings. No independent peer study validates them. Zero reconciliation weight avoids treating market-anchored cases as independent intrinsic evidence.',
      'selected_ev_ebitda':'20x/25x/30x are analyst multiple stress cases, below the approximate current operating multiple. No verified comparable-company set; these are not CCA recommendations and receive zero reconciliation weight.',
      'net_borrowing':'No incremental net borrowing assumed. Historical borrowing has changed materially, so this is a bridge convention, not a verified debt policy. FCFE valuation is excluded.',
      'nonoperating_income':'Hold FY26 other income INR224.03cr less equity-accounted loss INR30.09cr at INR193.94cr. Approximate treasury/JV income for the interim equity-cash bridge and multiple stress cases; not included in operating DCF EBIT.',
      'nci_profit':'Hold reported FY26 minority profit INR3.52cr. Minority equity is separately deducted at carrying-value proxy in the enterprise/equity bridge.',
      'shares_change':'No share issuance assumed; supplied annual statements show 240868296 diluted shares. This is not a guarantee that no corporate action occurred after the financial year.',
      'equity_proceeds':'No issuance or repurchase proceeds assumed; explicit zero financing convention.',
      'other_equity_changes':'Zero OCI forecast is a convention, not reported clean surplus; actual FY26 parent OCI was nonzero. Residual income remains excluded.',
      'dividend_payout':'75-85% payout estimates reference the mature distribution history. This run excludes DDM because future cash payment dates and a reconciled dividend calendar are missing.',
      'terminal_value_limit':'75% terminal-value dependence is an analyst review threshold, not a universal rule.',
      'method_divergence_limit':'50% relative method dispersion is an analyst investigation threshold, not a statistical confidence level.'
    }
    for driver,scenarios in case_values.items():
        for i,scenario in enumerate(['bear','base','bull']):
            risk=driver in ('risk_free_rate','beta','equity_risk_premium','terminal_growth','terminal_roic','terminal_roe','selected_pe','selected_ev_ebitda')
            record=Assumption(company='britannia',driver=driver,scenario=scenario,values=[str(x) for x in scenarios[i]],
                source_type='analyst_assumption',source=call if driver in ('volume_growth','price_mix_growth','ebitda_margin') else annual,
                source_date='2026-10-18',confidence='low' if risk else 'medium',rationale=explanations[driver],
                derivation=explanations[driver],override=False)
            assumptions.save(record,reason='Dated Britannia source-calibrated analyst case; explicit estimates, no universal FMCG defaults')
    methods=[]
    exclusions={
      'FCFE':'Excluded: historical borrowing changes and interim financing policy not established; no-borrowing bridge assumption is insufficient to validate FCFE.',
      'DDM':'Excluded from this run: stable mature dividends may support DDM, but payment dates and first-year cash-dividend timing require a reconciled schedule.',
      'Residual income':'Excluded: OCI and balance-date roll-forward need clean-surplus reconciliation; do not present zero assumed OCI as a historical fact.',
      'NAV':'Excluded: book assets omit internally generated brand/distribution economics and independently realizable values are absent.',
      'SOTP':'Excluded: audited group is reported as one Foods operating segment; reliable separate segment earnings/valuations are absent.',
    }
    for name in METHODS:
        yes=name in ('DCF FCFF','Forward P/E','EV/EBITDA')
        reason=('Primary conditional intrinsic method: sourced operating history and explicit scenario assumptions; rate and interim cash bridge remain estimates.' if name=='DCF FCFF'
                else 'Secondary analyst-multiple stress test only; no independent peer validation and no reconciliation weight.' if yes
                else exclusions.get(name,'Excluded: no verified comparable transactions/peers, or profitability makes this denominator an inferior primary measure.'))
        methods.append({'method':name,'applicable':'Yes' if yes else 'No','importance':'High' if name=='DCF FCFF' else 'Low',
                        'reason':reason,'weight':1 if name=='DCF FCFF' else 0,
                        'weight_rationale':'Only the conditional operating DCF has an independently specified cash-flow basis; no false diversification across market-anchored multiples.' if name=='DCF FCFF' else 'Excluded or unvalidated cross-check; zero weight.'})
    research=[
      {'topic':'Profit normalization','finding':'Reported FY26 parent PAT INR2533.49cr rose 16.3%. Net prior-year tax adjustments reduced tax expense by INR82.10cr; removing that item gives approximately INR2451.39cr and about 12.5% profit growth. The gross favorable-order reversal of INR95.39cr is a different disclosure. Do not subtract both.','source':'FY26 annual report PDF pp132 and146, Note19(c).'},
      {'topic':'Historical one-off','finding':'FY23 exceptional income INR375.60cr relates to the dairy/Bel transaction. Reported FY23 EPS is not a clean recurring baseline; neither that gain nor the subsequent PAT decline should be extrapolated mechanically.','source':'FY23 report PDF p114; NSE corporate filing 5-May-2023.'},
      {'topic':'Demand and pricing','finding':'Q1 FY27 net sales INR4964cr, +9.5%; management confirmed 9% tonnage growth. Exact implied price/mix on these rounded figures is about 0.46%, not 0.5% as an additive identity. This net-sales basis is not identical to audited revenue from operations.','source':'Q1 FY27 deck PDF pp18-19; 7-Aug-2026 transcript PDF p15.'},
      {'topic':'Margin risk','finding':'General trade recovered and adjacencies grew faster, but fuel, laminates and advertising spending constrain margins. Management said pricing had mitigated only part of inflation. A smooth margin expansion is a forecast assumption.','source':'7-Aug-2026 transcript PDF pp5-8; Q1 deck pp16-19.'},
      {'topic':'Cash generation','finding':'FY26 operating cash flow INR2611.60cr and gross cash capex INR205.57cr. CFO less capex INR2406.03cr is not identical to FCFF: interest, tax, working-capital and non-operating classifications differ. The 1.07% capex/revenue ratio is not extrapolated forever.','source':'FY26 report PDF pp133-134.'},
      {'topic':'Negative working capital','finding':'Core trade NWC was negative INR81.27cr. Supplier funding supports cash conversion, but incentives receivable, other operating assets/liabilities and provisions remain outside this narrow proxy. Their future net changes are assumed neutral.','source':'FY26 report PDF p132 and146.'},
      {'topic':'Non-operating value','finding':'Financial investments, loans, associates/JV and investment property are added once at INR3727.66cr carrying-value proxy; this is not a fair-value appraisal. Interest/JV results are excluded from operating EBIT to avoid double counting.','source':'FY26 report PDF pp132,144-146.'},
      {'topic':'Valuation-date estimate','finding':'The model date is 16-Oct-2026. It prorates first-year cash flows uniformly, rolls the 31-Mar-2026 bridge using estimated interim FCFE, and deducts the INR90.50/share distribution as an explicit paid/distribution assumption. No September balance sheet is asserted.','source':'Market timing/bridge inputs; annual report dividend recommendation and NSE ex-date 31-Jul-2026.'},
      {'topic':'Discount rate','finding':'The nominal-INR risk-free proxy, beta and equity premium are analyst assumptions. They are not a verified same-day CAPM estimate. These are major valuation sensitivities and keep confidence low.','source':'Assumption register. Official current yield / regression-beta validation incomplete.'},
      {'topic':'Triangulation limitation','finding':'P/E and EV/EBITDA outputs are multiple stress cases with zero weighting because no independently verified peer set was supplied. The final weighted row equals DCF deliberately; it is not a corroborated multi-method fair value.','source':'Methods and Multiple policy.'},
      {'topic':'Latest update scope','finding':'The local corpus and official online checks include the Q1 FY27 call and FY26 audited filing. No Q2 FY27 financial results were established during this run. An absence in these checks does not establish that no later announcement exists.','source':'Official company investor page, NSE FY26 integrated filing, and 7-Aug-2026 call.'},
    ]
    case={'as_of':'2026-10-18','revenue_route':'Volume and price/mix','margin_route':'EBITDA margin','methods':methods,
      'market':{'price_date':'2026-10-16','price':4764,'current_shares':240868296,'diluted_shares':240868296,
        'debt':13802800000,'cash':2200000000,'nci':293200000,'preferred':0,'nonoperating_assets':37276600000,
        'quote_source':'NSE indexed quote BRITANNIA INR4764; cross-check ET historical close 16-Oct-2026. Live quote delivery incomplete.',
        'shares_date':'2026-03-31','balance_date':'2026-03-31','accounting_scope':'consolidated','currency':'INR',
        'lease_policy':'Gross debt includes INR22.45cr lease liabilities; reported EBITDA is post-Ind AS116. No separate double deduction of leases.',
        'valuation_date':'2026-10-16','interim_dividends':21798580788},
      'market_notes':['All balance inputs start at 31-Mar-2026, not an asserted October balance. Each scenario estimates the interim equity-cash bridge.',
         'INR90.50/share distribution after balance date is deducted in full. Paid status is an explicit case assumption based on the announced distribution/ex-date; bank settlement was not verified.',
         'Carrying values proxy the non-operating portfolio and minority claims. Quotes, share count and balance dates differ and require refresh.',
         'First forecast-year cash flows accrue uniformly. This estimated timing bridge does not replace reported interim cash flow; all three scenarios expose it.'],
      'research_notes':research,
      'issues':['Conditional analyst scenarios: capital costs, terminal returns and multiple ranges are estimates, not independently verified market facts.',
         'Current cash/debt bridge estimated from March balances; uniform interim cash accrual and distribution timing require review.',
         'No peer-backed CCA, transaction valuation, or native desktop Excel verification.']}
    case['drivers']=[{'driver':name,'source_type':kind,'confidence':'medium','source':source} for name,kind,source in [
      ('Tonnage and volume growth','historical','7-Aug-2026 call PDF p15: 9% tonnage growth, not pack-count growth.'),
      ('Pricing versus commodity inflation','historical','7-Aug-2026 call PDF pp5-8: fuel/laminate costs and partial price recovery.'),
      ('General trade and e-commerce','historical','Q1 FY27 deck PDF p7: general trade recovery and faster other channels.'),
      ('Adjacencies and innovation','historical','7-Aug-2026 call PDF p4: croissant, dairy and other product growth.'),
      ('Advertising investment','management_guidance','7-Aug-2026 call PDF pp6-8: sustained brand investment and margin implications.'),
      ('Supplier-funded core trade cycle','historical','FY26 report PDF p132: inventory, receivables and trade payables.'),
      ('Capacity and cash capex','historical','FY23-26 consolidated cash-flow statements; FY26 report PDF p133.')]]
    dest=root/'config/company_cases/britannia.json';dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(case,indent=2),encoding='utf-8')
    print(json.dumps({'company':'britannia','assumptions':len(case_values)*3,'methods_calculated':['DCF FCFF','Forward P/E stress','EV/EBITDA stress'],'case_file':str(dest)}))

if __name__=='__main__':
    main()
