"""Company-specific analyst scenarios. These estimates are not reported facts."""
import json
from backend import storage, assumptions, excel_engine
from backend.valuation_spec import Assumption, METHODS

CASES = {
 'hul': dict(price=1893.8,shares=2349591262,diluted=2349889491,volume=[[.03]*5,[.05,.05,.045,.04,.04],[.07,.065,.06,.055,.05]],mix=[.01,.02,.03],
   margins=[[.22]*5,[.235,.237,.24,.24,.24],[.245,.25,.255,.26,.26]],da=.021,capex=[.028,.022,.018],nwc=[-.06,-.08,-.09],
   beta=[1,.8,.65],g=[.03,.04,.05],roic=[.2,.3,.4],payout=[.85,.9,.95],pe=[30,38,46],ev=[20,26,32],
   nonop=7360000000,nci_profit=190000000,claims=6180000000,distribution=22,
   reason='Q1 FY27 underlying volume grew 5% and sales 10%. Home care and beauty led growth while palm-cost pressure affected personal care. Forecast volume fades, pricing varies by scenario, and EBITDA margin is calibrated to 23.35% FY26 continuing operations.',
   weights={'DCF FCFF':.7,'DDM':.3},
   notes=[('Continuing earnings','FY26 total parent PAT includes ice-cream demerger effects. Use continuing parent PAT INR10633cr and operating EBITDA INR15054cr. The INR4611cr demerger gain is excluded from recurring forecasts.','Annual report PDF419,445; annual result PDF8,12.'),
    ('Cash-flow comparability','Continuing CFO: FY26 10999 - (-72) = 11071cr; FY25 11886 - 94 = 11792cr. Total cash capex1361cr is not continuing-only capex. Forecast capex remains explicit 1.8%-2.8% sales judgment. Group cash dividends10124cr/FY26 and12473cr/FY25 are not continuing-segment allocations.','FY2026 annual report PDF370-371,446; annual result PDF11.'),
    ('Acquisition claims','Deduct the INR618cr acquisition liability once. Other non-trade operating balances and pension settlement schedules are not fully projected. Core trade NWC is a narrow proxy.','Annual report PDF407.'),
    ('Dividend method','Regular payout 91% in FY26 and 95% in FY25 supports a secondary multi-stage DDM. Forecast payout 85%-95%, with terminal payout constrained by sustainable ROE. Cash distributions are uniformly prorated, not an exact payment calendar.','Annual report PDF419.')]),
 'nestle-india':dict(price=1265.5,shares=1928314320,diluted=1928314320,volume=[[.08,.06,.05,.04,.04],[.12,.10,.09,.08,.07],[.16,.13,.11,.10,.09]],mix=[.01,.025,.04],
   margins=[[.22]*5,[.237,.24,.24,.24,.24],[.25,.255,.26,.26,.26]],da=.03,capex=[.045,.038,.032],nwc=[.02,0,-.01],
   beta=[1,.85,.7],g=[.03,.045,.055],roic=[.2,.3,.4],payout=[.6,.7,.8],pe=[40,52,64],ev=[27,35,43],
   nonop=-51700000,nci_profit=0,claims=20898300000,distribution=5,
   reason='The 15-Oct-2026 Q2 disclosure reports double-digit volume growth and sales growth20.5%, with advertising up46% and EBITDA margin23.8%. Forecasts incorporate stronger volume than a FY26-only extrapolation, fade to mature growth and stress cocoa, milk and edible-oil costs. Exact volume/price split is analyst judgment, not disclosed guidance.',
   weights={'DCF FCFF':.8,'DDM':.2},
   notes=[('New September results','15-Oct-2026 official company filing establishes Q2 sales growth20.5%, double-digit volume growth, advertising/marketing spending up46% and EBITDA margin23.8%. These management-release figures are standalone. The consolidated statement is separately included in the same filing. Forecasts use this direction without treating the unspecified volume/price split as fact.','https://www.nestle.in/sites/g/files/pydnoa451/files/2026-10/BSENSEOutcomeResults15102026signed.pdf pp7,13-15; accessed through public search, direct archive download returned403.'),
    ('Bonus and fiscal period','Shares doubled on11-Aug-2025. FY26 current denominator is1928314320 shares. FY25 closing shares are unadjusted history; published comparative EPS is bonus-adjusted. The fifteen-month FY2023-24 transition is not treated as a twelve-month comparable.','FY26 annual report PDF134.'),
    ('Retirement obligations','DCF deducts INR2089.83cr pension/gratuity carrying liabilities (noncurrent18326.4m + current2571.9m) as an explicit debt-like proxy. The model does not pretend these are bank borrowings. Funding timetable, taxes and other contingencies require further work.','Annual report PDF137, Note20.'),
    ('Dividend method','Secondary DDM uses lower forecast payout than historical cash dividends/earnings to allow reinvestment and retirement funding. It is a policy scenario, not declared future dividends.','Annual report PDF119,134,137.')]),
 'itc':dict(price=263.5,shares=12529468231,diluted=12529468231,growth=[[0,.02,.03,.03,.03],[.04,.05,.06,.06,.05],[.08,.09,.09,.08,.07]],
   margins=[[.30,.30,.305,.31,.31],[.335,.34,.345,.345,.345],[.35,.355,.36,.36,.36]],da=.022,capex=[.035,.03,.028],nwc=[.24,.22,.20],
   beta=[1.1,.9,.75],g=[.025,.035,.045],roic=[.15,.22,.3],payout=[.75,.85,.9],pe=[13,17,21],ev=[9,12,15],
   nonop=28028800000,nci_profit=3286800000,claims=0,distribution=8.25,
   reason='Group growth is constructed as a judgment across cigarettes, other FMCG, agri, paper and other businesses. FY26 revenue is net of excise to avoid interpreting higher tax pass-through as economic growth. Cigarette taxation and illicit-trade substitution constrain the downside. Group EBITDA margin is a mix approximation and SOTP values each segment separately.',
   weights={'DCF FCFF':.4,'DDM':.3,'SOTP':.3},
   notes=[('Tax pass-through','FY26 gross operating revenue INR89913.33cr includes excise INR11044.93cr. Model revenue is net INR78868.40cr. Operating EBITDA remains INR27317.91cr because excise is removed from both revenue and expenses. A gross revenue surge does not establish volume growth.','FY26 annual report PDF253.'),
    ('Hotel demerger','FY25 total consolidated PAT INR35052.48cr includes discontinued operations and a large demerger effect. It is not the recurring earnings baseline. Retained equity-method hotel exposure is included only in nonoperating investments, not a hotel operating segment.','FY26 annual report PDF252-253,325.'),
    ('Segment differences','Cigarettes, branded foods, agri and paper have different economics. SOTP applies explicit scenario-specific EBIT multiples to each disclosed segment and capitalises corporate costs separately. Multiples are analyst judgments pending sector-matched peer evidence.','FY26 annual report PDF325.'),
    ('Financing and share changes','FY26 net borrowing changed sharply and employee share issues occurred. FCFE is excluded as a primary method. No new equity issuance is assumed in the forecast. Current fully diluted option allocation remains a limitation.','Annual report PDF257,291.'),
    ('Dividend cross-check','Long regular distributions support a secondary DDM. Its payout assumptions and terminal ROE are explicit judgments and not independent confirmation of DCF.','Annual report PDF254,257.')]),
 'tata-consumer':dict(price=978.9,shares=989561780,diluted=989561780,growth=[[.06,.05,.05,.05,.05],[.12,.11,.10,.09,.08],[.16,.14,.13,.12,.10]],
   margins=[[.125]*5,[.14,.145,.15,.155,.155],[.15,.16,.165,.17,.17]],da=.031,capex=[.04,.033,.03],nwc=[.06,.04,.03],
   beta=[1.2,1,.85],g=[.03,.045,.055],roic=[.12,.18,.25],payout=[.35,.45,.55],pe=[35,45,55],ev=[20,26,32],
   nonop=740500000,nci_profit=45000000,claims=596800000,distribution=10,
   reason='Q1FY27 India volume13%, growth-business sales47%, tea pricing pass-through and international FX translation support a category mix forecast, not one group volume figure. Base growth12% fades to8%, while margin13.6% in Q1 gradually improves with integration and growth-business scale.',
   weights={'DCF FCFF':1},
   notes=[('Mix versus pricing','Q1FY27 India tea volume rose2% while revenue fell4% as costs were passed through. Growth businesses grew47% and represented36% of India revenue. Group growth is not a simple common volume multiplied by one price assumption.','Q1FY27 deck PDF5-6.'),
    ('Treasury reconciliation','Use balance-sheet cash INR3046.57cr and gross borrowings including overdrafts. Cash-flow closing cash INR1412.79cr already subtracts INR1633.78cr overdrafts. Using that net cash and deducting overdraft again would double count debt.','Official FY26 consolidated statements PDF12,16.'),
    ('Minority purchase commitments','INR1330.90cr put/call purchase commitments concern fully consolidated subsidiaries with NCI. This case deducts reported INR1401.33cr NCI at carrying proxy and separately INR59.68cr contingent consideration. It does not deduct the put liability again. Contract-by-contract minority fair-value reconciliation is unresolved and could materially change equity value.','Official annual consolidated statements PDF17,47,56.'),
    ('Associate losses','Equity-method results of negative INR90.70cr are excluded from operating EBIT. Associate/JV carrying values are added once in the bridge. Starbucks sales are not consolidated group revenue and are not assigned a standalone positive enterprise value without a segment model.','Official FY26 statements PDF13,59.'),
    ('Method exclusions','Low payout and continuing portfolio reinvestment make DDM a weak primary method. NAV omits brands. SOTP awaits separate regional/segment forecasts and matched peer evidence. P/E and EV/EBITDA are visible multiple stress cases with zero weight.','Case-specific method selection.')])
}


def main():
    for company,c in CASES.items():
        package=excel_engine.company_package(company)
        f={k:v[-1] for k,v in package['financials'].items()}
        provenance='Source-reviewed FY26 consolidated statements and latest local earnings presentation. '+c['reason']
        values={
         'ebitda_margin':c['margins'],'da_ratio':[[c['da']]*5]*3,'capex_ratio':[[v]*5 for v in c['capex']],
         'nwc_ratio':[[v]*5 for v in c['nwc']],'tax_rate':[[.26 if company=='nestle-india' else .25]*5]*3,
         'risk_free_rate':[[.074]*5]*3,'beta':[[v]*5 for v in c['beta']],'equity_risk_premium':[[.06]*5]*3,
         'pretax_cost_debt':[[.09]*5]*3,'debt_weight':[[f['debt']/(c['price']*c['shares']+f['debt'])]*5]*3,
         'terminal_growth':[[v]*5 for v in c['g']],'terminal_roic':[[v]*5 for v in c['roic']],
         'terminal_roe':[[v]*5 for v in c['roic']],'net_borrowing':[[0]*5]*3,
         'interest_rate':[[.08]*5]*3,'nonoperating_income':[[c['nonop']]*5]*3,
         'nci_profit':[[c['nci_profit']]*5]*3,'shares_change':[[0]*5]*3,'equity_proceeds':[[0]*5]*3,
         'other_equity_changes':[[0]*5]*3,'dividend_payout':[[v]*5 for v in c['payout']],
         'selected_pe':[[v]*5 for v in c['pe']],'selected_ev_ebitda':[[v]*5 for v in c['ev']],
         'terminal_value_limit':[[.75]*5]*3,'method_divergence_limit':[[.5]*5]*3}
        if 'volume' in c:
            values['volume_growth']=c['volume'];values['price_mix_growth']=[[v]*5 for v in c['mix']]
        else:values['direct_revenue_growth']=c['growth']
        reasons={
         'risk_free_rate':'7.4% nominal INR analyst rate proxy. Not a verified same-day government yield. Major sensitivity, low confidence.',
         'equity_risk_premium':'6% analyst equity-risk premium over the nominal INR proxy, with no separate double-counted country premium. Not a measured current market fact.',
         'beta':'Company-specific scenario risk coefficients, not a regression beta. '+str(c['beta']),
         'terminal_growth':'Company-specific nominal perpetual-growth scenarios '+str(c['g'])+'. Terminal reinvestment is constrained by sustainable ROIC/ROE. Not management guidance.',
         'terminal_roic':'Company-specific sustainable terminal-return scenarios '+str(c['roic'])+'. These limit perpetual growth through reinvestment.',
         'terminal_roe':'Company-specific sustainable terminal ROE '+str(c['roic'])+'. Terminal dividends cannot exceed sustainable earnings after reinvestment.',
         'selected_pe':'Explicit analyst forward multiple stress cases '+str(c['pe'])+'. Historical market references are context only. No peer-backed recommendation; zero reconciliation weight.',
         'selected_ev_ebitda':'Explicit analyst forward EBITDA multiple stress cases '+str(c['ev'])+'. Quality and growth differ across categories. No independent peer validation; zero reconciliation weight.',
         'nonoperating_income':'FY26 treasury/other income less equity-method losses, or plus associate profits, held flat as an earnings-bridge estimate. Excluded from operating DCF EBIT and not capitalised again there.',
         'net_borrowing':'Explicit no-new-net-borrowing forecast convention. This does not establish stable debt policy or justify FCFE automatically.',
         'shares_change':'Zero incremental issuance convention. Closing shares are dated31-Mar-2026. Later issues/options require dilution review.',
         'other_equity_changes':'Zero future OCI convention. Historical OCI is nonzero and not assumed clean surplus. Residual income is excluded.',
         'dividend_payout':'Company-specific payout scenarios '+str(c['payout'])+'. Assess alongside capex and funding needs. Forecast distributions are not declared dividends.',
         'capex_ratio':'Company-specific capex/revenue scenarios '+str(c['capex'])+' calibrated to capacity investment and cash capex. Future acquisition spending is excluded and must be separately financed.',
         'nwc_ratio':'Company-specific core trade NWC/revenue scenarios '+str(c['nwc'])+'. Latest reviewed core NWC ratio '+str(round(f['operating_nwc']/f['revenue'],4))+'. Other operating balance changes assumed neutral.',
         'da_ratio':'Company-calibrated D&A/revenue '+str(c['da'])+'. A ratio approximation, not a vintage-level asset schedule.',
         'tax_rate':'Normalised operating tax estimate, not extrapolation of one-off tax credits or jurisdiction-specific effective tax. Review subsidiaries and deductibility.',
         'nci_profit':'FY26 minority profit held flat as an explicit attributable earnings approximation. Minority value is deducted separately in the enterprise/equity bridge.',
         'interest_rate':'8% opening debt interest-cost estimate. Lease interest and financing composition differ. No live refinancing quote is asserted.',
         'pretax_cost_debt':'9% explicit financing stress assumption, not a lender quote.',
         'debt_weight':'Gross debt divided by dated market equity plus gross debt. Other claims are not assumed interest-bearing financial debt.',
         'equity_proceeds':'No new equity issuance or repurchase assumed.',
         'terminal_value_limit':'75% terminal-value dependence is a review threshold, not a confidence interval.',
         'method_divergence_limit':'50% method dispersion is a review threshold, not an averaging rule.'}
        for driver,scenarios in values.items():
            reason=reasons.get(driver,c['reason'])
            for i,scenario in enumerate(('bear','base','bull')):
                assumptions.save(Assumption(company=company,driver=driver,scenario=scenario,values=[str(v) for v in scenarios[i]],
                    source_type='analyst_assumption',source=provenance[:1900],source_date=storage.today_ist(),confidence='low',
                    rationale=reason,derivation=reason,override=False),reason='Company-specific source-calibrated scenario build, preserving manual overrides')
        methods=[]
        for method in METHODS:
            enabled=method in c['weights'] or method in ('Forward P/E','EV/EBITDA')
            reason=(
              'Conditional intrinsic cash-flow method using sourced statements and explicit company-specific scenarios.' if method=='DCF FCFF' else
              'Secondary dividend-policy cross-check for a mature regular distributor; payout, timing and terminal returns remain estimates.' if method=='DDM' and enabled else
              'Distinct cigarette, FMCG-other, agri, paper and other EBIT valuations. Multiples are analyst stress ranges, not independently verified peers.' if method=='SOTP' and enabled else
              'Analyst forward multiple stress cases, not peer-backed CCA. Zero reconciliation weight.' if method in ('Forward P/E','EV/EBITDA') else
              'Excluded: no verified matching transaction consideration, ownership, enterprise-value and financial denominator.' if method.startswith('Precedent') else
              'Excluded: unstable financing or incomplete cash distribution policy prevents a reliable equity-cash-flow interpretation.' if method=='FCFE' else
              'Excluded: historical OCI and equity adjustments have not been reconciled to clean surplus.' if method=='Residual income' else
              'Excluded: no independently justified realizable asset values; book values omit brand economics.' if method=='NAV' else
              'Excluded: segment forecasts, ownership-adjusted values or suitable evidence not sufficient for this method.' if method=='SOTP' else
              'Excluded: payout is not representative of the reinvestment-led business valuation.' if method=='DDM' else
              'Excluded: inferior denominator or no suitable matched-period peers; correlated multiples add no independent evidence.')
            weight=c['weights'].get(method,0)
            methods.append(dict(method=method,applicable='Yes' if enabled else 'No',importance='High' if weight else 'Low',reason=reason,weight=weight,
                weight_rationale='Analyst reconciliation based on cash-flow visibility and company suitability; correlated methods are not independent proof.' if weight else 'Excluded or unvalidated multiple cross-check, zero weight.'))
        market={k:f[k] for k in ('debt','cash','nci','preferred','nonoperating_assets')}
        market.update(price=c['price'],price_date='2026-10-16',valuation_date='2026-10-19',current_shares=c['shares'],diluted_shares=c['diluted'],
            shares_date='2026-03-31',balance_date='2026-03-31',accounting_scope='consolidated',currency='INR',
            other_senior_claims=c['claims'],interim_dividends=c['distribution']*c['shares'],
            lease_policy='Borrowings and lease liabilities deducted once, with post-Ind AS116 operating EBITDA. Renewal-lease capex requires review.',
            quote_source='NSE India home market display,16-Oct-2026 close, accessed19-Oct-2026. https://www.nseindia.com/ . Not a live19-Oct quote.')
        case=dict(as_of=storage.today_ist().isoformat(),market=market,methods=methods,revenue_route='Volume and price/mix' if 'volume' in c else 'Direct disclosed drivers',
            margin_route='EBITDA margin',direct_growth_rationale=c['reason'],
            drivers=[dict(driver=c['reason'],source_type='historical',confidence='medium',source='FY26 consolidated statements and latest result presentation')],
            research_notes=[dict(topic=t,finding=finding,source=s) for t,finding,s in c['notes']],
            market_notes=['31-Mar-2026 balance and share basis rolled forward with estimated uniform interim FCFE, not a reported October balance.',
                f'Assume INR{c["distribution"]} per share distribution after balance date. Payment timing is an explicit analyst case assumption, not independently confirmed bank settlement.',
                '16-Oct close is the last dated reference used here. Latest intraday prices and later dilution are not asserted.',
                'Other debt-like claims and nonoperating assets are carrying-value proxies. Minority buyout, pension and lease policies are described in Research.'],
            issues=['Conditional analyst scenarios, not a precise fair-value recommendation. Capital costs, terminal returns, current cash bridge and multiples require analyst review.',
                'Only FY25/FY26 annual statements reviewed for this new build. Earlier years left unavailable rather than manufactured.',
                'No verified category-matched peer-forward estimate set or transaction database. Market multiples have zero reconciliation weight.',
                'Native desktop Excel recalculation not verified. News checks may be incomplete and unverified headlines never change numerical forecasts automatically.'])
        if company=='hul':case['issues'].append('Continuing CFO reconciled using discontinued-operation disclosures. Continuing-only historical capex remains unavailable; net investing cash flow is not substituted for capex.')
        if company=='tata-consumer':case['issues'].append('Minority put/call settlement and corresponding NCI derecognition remain unresolved; reported NCI is a carrying-value proxy.')
        if company=='itc':
            case['segments']=[dict(name=name,ebit=ebit*10000000,multiples=multiples,growth=growth,source='FY26 consolidated annual report PDF325. EBIT multiples and one-year growth are analyst scenarios, not sourced peer targets.')
                for name,ebit,multiples,growth in [
                 ('Cigarettes',22245.62,[12,15,18],[-.05,0,.05]),('FMCG other',1811.82,[18,22,26],[.08,.12,.16]),
                 ('Agri',1584.24,[9,11,13],[0,.05,.10]),('Paper and packaging',754.06,[9,11,13],[-.05,0,.06]),('Other',670.40,[10,12,14],[.02,.05,.08])]]
            case['segment_corporate_cost']=1320*10000000
        target=storage.PROJECT_DIR/'config/company_cases'/f'{company}.json'
        target.write_text(json.dumps(case,indent=2),encoding='utf-8')
        print(company,'configured',len(values)*3,'assumptions; methods:',','.join(c['weights']))


if __name__=='__main__':main()
