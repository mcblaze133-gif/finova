"""Prepare evidence packages for formula-driven Excel workbooks.

This module does not calculate valuations. Only explicit reviewed source inputs
and labelled assumptions enter an export. Existing exports are never refreshed
or overwritten automatically, preserving edits made directly in Excel.
"""
import asyncio
import json
import re
from datetime import date
from pathlib import Path
from uuid import uuid4
from backend import storage, library, assumptions
from backend.valuation_spec import METRICS, METHODS, DRIVERS, SCENARIOS, finite
from backend.evidence_packs import digest_file


def input_fingerprint(package):
    import hashlib
    semantic = {k: v for k, v in package.items() if k != 'created_at'}
    code = {p.name: digest_file(p) for p in (storage.PROJECT_DIR / 'excel').glob('*.mjs')}
    # Include authoring dependency versions and backend input semantics.
    for p in (storage.PROJECT_DIR / 'package-lock.json', Path(__file__),
              storage.PROJECT_DIR / 'backend/valuation_spec.py'):
        if p.exists():
            code[str(p.name)] = digest_file(p)
    return hashlib.sha256(json.dumps([semantic, code], sort_keys=True).encode()).hexdigest()


def cached_export(fingerprint):
    rows = storage.rows('SELECT e.*,c.workbook_sha256 FROM excel_export_cache c JOIN excel_exports e ON e.id=c.export_id WHERE c.input_hash=?', (fingerprint,))
    if rows:
        row = rows[0]
        path = Path(row['workbook_path']).resolve() if row['workbook_path'] else None
        if (row['status'] == 'exported' and path and path.is_relative_to((storage.PROJECT_DIR / 'outputs').resolve())
                and path.is_file() and digest_file(path) == row['workbook_sha256']):
            return row
    return None


def normalized_value(record):
    factor = {'INR_lakh': 100000, 'INR_crore': 10000000}.get(record.unit, 1)
    return float(finite(record.value) * factor)


def company_package(company, update_run_id=None):
    if not re.fullmatch(r'[a-z0-9-]{2,60}', company):
        raise ValueError('Use a registered company ID or a simple lower-case company slug.')
    records = library.company_records(company)
    hashed = [r for r in records if r.source_sha256]
    stale = []
    source_hashes = {}
    for record in hashed:
        path = (library.root_folder() / record.source_file).resolve()
        if path not in source_hashes:
            source_hashes[path] = digest_file(path) if path.is_relative_to(library.root_folder()) and path.is_file() else None
        if (not path.is_relative_to(library.root_folder()) or not path.is_file()
                or source_hashes[path] != record.source_sha256):
            stale.append(record)
    eligible = [r for r in records if r.review_status in ('user_verified', 'source_verified') and r.source_type == 'historical'
                and r.segment == 'group' and r.source_date <= storage.today_ist() and r.period_end <= storage.today_ist() and r not in stale]
    from backend import financial_history
    history = financial_history.build(company, eligible)
    case_file = storage.PROJECT_DIR / 'config' / 'company_cases' / f'{company}.json'
    case = json.loads(case_file.read_text(encoding='utf-8')) if case_file.exists() else {}
    # The historical appendix preserves other reported bases. Forecast actuals
    # must still use one explicitly selected basis; never select by recency alone.
    selected_basis = case.get('historical_model_basis')
    if selected_basis:
        eligible = [r for r in eligible if [r.accounting_scope,r.operations_scope] == selected_basis]
    # A company workbook must have one explicit accounting/operations basis.
    bases = {(r.accounting_scope, r.operations_scope) for r in eligible}
    issues = [f'{len(stale)} source-linked records excluded: source files changed or are missing. Re-review required.'] if stale else []
    if len(bases) > 1:
        eligible = []
        issues.append('Mixed accounting or operations scopes. Select and reconcile one reporting basis before export.')
    basis = next(iter(bases)) if len(bases) == 1 else None
    annual_revenues = [r for r in eligible if r.metric == 'revenue' and r.period_start
                       and 330 <= (r.period_end - r.period_start).days + 1 <= 400]
    periods = sorted({r.period_end for r in annual_revenues})[-5:]
    matrix = {metric: [None] * 5 for metric in METRICS}
    period_labels = [None] * (5 - len(periods)) + [d.isoformat() for d in periods]
    source_rows = []
    for index, label in enumerate(period_labels):
        if label is None:
            continue
        for metric in METRICS:
            matches = [r for r in eligible if r.metric == metric and r.period_end.isoformat() == label]
            flow = metric in ('revenue', 'ebitda', 'da', 'ebit', 'net_income', 'cfo', 'capex', 'dividends', 'interest')
            if flow:
                matches = [r for r in matches if r.period_start and 330 <= (r.period_end-r.period_start).days+1 <= 400]
                revenue_starts = {r.period_start for r in annual_revenues if r.period_end.isoformat() == label}
                matches = [r for r in matches if r.period_start in revenue_starts]
            values = {normalized_value(r) for r in matches}
            if len(values) > 1:
                issues.append(f'Conflicting reviewed {metric} values for {label}; no value selected.')
            elif len(values) == 1:
                matrix[metric][index] = next(iter(values))
                for record in matches:
                    source_rows.append(record.model_dump(mode='json'))
    try:
        from backend.companies import resolve
        display_name = resolve(company).legal_name
    except ValueError:
        display_name = company.replace('-', ' ').title()
    last = {key: values[-1] for key, values in matrix.items()}
    methods = []
    for method in METHODS:
        reason = 'Financial evidence and method-specific suitability must be established.'
        applicable = 'Conditional'
        importance = 'Unassessed'
        if method in ('Forward P/E', 'PEG') and last['net_income'] is not None and last['net_income'] <= 0:
            applicable, reason = 'No', 'Nonpositive current attributable earnings; a normalized positive forward basis is required.'
        elif method == 'DDM':
            reason = 'Requires documented stable payout policy and dividends consistent with sustainable distributable cash.'
        elif method == 'FCFE':
            reason = 'Requires an interpretable, explicit financing policy and equity cash-flow forecast.'
        elif method == 'Residual income':
            reason = 'Requires meaningful book equity, clean-surplus reconciliation and justified sustainable ROE.'
        elif method == 'NAV':
            reason = 'Requires dated economically relevant asset values and all senior liabilities.'
        elif method == 'SOTP':
            reason = 'Requires distinct material segments, ownership and a consistent enterprise/equity bridge.'
        elif method.startswith('Precedent'):
            reason = 'Requires comparable sourced transactions; consideration and ownership acquired do not establish enterprise value.'
        methods.append({'method': method, 'applicable': applicable, 'importance': importance,
                        'reason': reason, 'weight': None, 'weight_rationale': None})
    source_inventory = library.inventory()
    package = {'company_id': company, 'company': display_name, 'created_at': storage.now(),
            'currency': 'INR', 'amount_basis': 'plain INR and actual shares',
            'source_folder': source_inventory['source_folder'], 'source_file_count': sum(1 for f in source_inventory['files'] if f['relative_path'].split('/')[0].casefold() == library.company_folder(company).name.casefold()),
            'periods': period_labels, 'financials': matrix, 'sources': source_rows,
            'historical_statements': history,
            'assumptions': [r['record'] for r in assumptions.list_for(company)],
            'methods': methods, 'drivers': library.observed_drivers(company), 'market': {}, 'peers': [], 'transactions': [], 'segments': [], 'assets': [],
            'driver_definitions': DRIVERS,
            'revenue_route': None, 'margin_route': None,
            'issues': issues + ([] if annual_revenues else ['No reviewed annual financial inputs are available.']),
            'limitations': ['Company-specific driver research and external updates must be verified before estimates are accepted.',
                            'CSV user_verified is an analyst assertion, not an automated verification of the PDF.',
                            'Native Excel calculation and optional connected-session assumption editing require separate verification.']}
    if case_file.exists():
        for key in ('market','methods','revenue_route','margin_route','research_notes','direct_growth_rationale','market_notes','drivers','segments','segment_corporate_cost','peers','transactions','assets','multiple_policy'):
            if key in case:
                package[key] = case[key]
        package['issues'].extend(case.get('issues', []))
        package['case_as_of'] = case.get('as_of')
    from backend import company_updates
    update = company_updates.get(company,update_run_id) if update_run_id else company_updates.latest(company)
    if update:
        package['external_updates'] = update
        result = update.get('result') or {}
        sources = {s['source_id']:s for s in result.get('sources', [])}
        notes = package.setdefault('research_notes', [])
        notes.append({'topic':'Online update coverage', 'finding':f"Checked {update['checked_at']}; {update['status']}. "+
                      ' '.join(result.get('limitations', []))+' Events and news leads do not automatically change numerical assumptions.',
                      'source':f"Local refresh audit {update['id']}"})
        for event in result.get('events', []):
            notes.append({'topic':'Online event: '+event['headline'],
                          'finding':f"{event['fact_status']}. {event['mechanism']} Review: {', '.join(event.get('active_model_inputs',event['drivers_to_review']))}. {event['review_action']}",
                          'source':' | '.join(sources[i]['url'] for i in event['source_ids'] if i in sources)})
        for lead in result.get('news_leads', []):
            notes.append({'topic':'Unverified news lead: '+lead['headline'],
                          'finding':f"Published {lead['published_at']}; {lead['verification']}. Conditional interpretation: {lead['mechanism']}",
                          'source':lead['url']})
        package['issues'].append(f"Online refresh {update['status']}: {len(result.get('events', []))} assessed events, "
                                f"{len(result.get('news_leads', []))} unverified news leads. Review Research before treating valuations as current.")
    return package


def valuation_readiness(company, package=None):
    """Explain prerequisites before a run; a generated blank template is no valuation."""
    package = package or company_package(company)
    missing = []
    if not any(package['periods']):
        missing.append('Extract and validate annual financial figures from the company documents.')
    else:
        # Historical capex is useful calibration, but a forecast with an explicit
        # documented capex/revenue assumption need not invent a historical figure
        # where a demerger prevents a continuing-operations reconciliation.
        required = ('revenue','ebitda','da','operating_nwc','shares')
        absent = [metric.replace('_',' ') for metric in required if package['financials'][metric][-1] is None]
        if absent:
            missing.append('Validate the latest annual inputs: '+', '.join(absent)+'.')
    if not package['assumptions']:
        missing.append('Prepare company-specific bear, base and bull assumptions with sources and rationales.')
    else:
        scenarios = {a['scenario'] for a in package['assumptions']}
        if not set(SCENARIOS).issubset(scenarios):
            missing.append('Complete assumptions for all three valuation scenarios.')
    if package.get('revenue_route') not in ('Volume and price/mix','Direct disclosed drivers') or package.get('margin_route') not in ('Cost bridge','EBITDA margin'):
        missing.append('Establish the company-specific revenue and profitability forecast drivers.')
    if not any(m.get('applicable') == 'Yes' and m.get('weight') is not None and m['weight'] > 0 for m in package['methods']):
        missing.append('Select suitable valuation methods and justify their reconciliation weights.')
    if not all(package['market'].get(key) is not None for key in ('current_shares','debt','cash')):
        missing.append('Reconcile dated shares, debt and cash for the equity-value bridge.')
    weighted = [m for m in package['methods'] if m.get('weight') is not None and m['weight']>0]
    if weighted and (abs(sum(m['weight'] for m in weighted)-1)>1e-8 or
                     any(m.get('applicable')!='Yes' or not m.get('weight_rationale') for m in weighted) or
                     any(m.get('weight',0) is None or m.get('weight',0)<0 for m in package['methods'])):
        missing.append('Use nonnegative method weights totaling 100%, with suitability and a rationale for each included method.')
    cashflow = {m['method'] for m in weighted} & {'DCF FCFF','FCFE','DDM','Residual income'}
    if cashflow:
        required = {'da_ratio','tax_rate','capex_ratio','nwc_ratio','risk_free_rate','beta','equity_risk_premium',
                    'shares_change','equity_proceeds','net_borrowing','interest_rate','nonoperating_income','nci_profit'}
        required.update(('volume_growth','price_mix_growth') if package.get('revenue_route')=='Volume and price/mix' else ('direct_revenue_growth',))
        required.update(('gross_margin','advertising_ratio','employee_ratio','other_opex_ratio') if package.get('margin_route')=='Cost bridge' else ('ebitda_margin',))
        required.add('debt_weight')
        if cashflow & {'DDM','Residual income'}:
            required.add('dividend_payout')
        if 'Residual income' in cashflow:
            required.add('other_equity_changes')
        lookup = {(a['driver'],a['scenario']):a for a in package['assumptions']}
        gaps = []
        for scenario in SCENARIOS:
            drivers = required.copy()
            debt = lookup.get(('debt_weight',scenario),{}).get('values',[])
            if any(v is not None and finite(v)>0 for v in debt):
                drivers.add('pretax_cost_debt')
            for driver in sorted(drivers):
                values = lookup.get((driver,scenario),{}).get('values',[])
                if len(values)!=5 or any(v is None for v in values):
                    gaps.append(f'{scenario} {driver}')
            terminal = {'terminal_growth'} | ({'terminal_roic'} if 'DCF FCFF' in cashflow else set()) | ({'terminal_roe'} if cashflow & {'FCFE','DDM','Residual income'} else set())
            for driver in sorted(terminal):
                values = lookup.get((driver,scenario),{}).get('values',[])
                if not values or values[0] is None:
                    gaps.append(f'{scenario} {driver}')
        if gaps:
            missing.append('Complete required forecast inputs: '+', '.join(gaps)+'.')
        if package.get('revenue_route')=='Direct disclosed drivers' and not package.get('direct_growth_rationale'):
            missing.append('Document the operating drivers behind the direct revenue-growth forecast.')
    if any(a.get('source_date','')>storage.today_ist().isoformat() for a in package['assumptions']):
        missing.append('Assumption source dates cannot be in the future.')
    return {'can_build':not missing,'missing':missing}


async def export_company(company, export_id=None, *, refresh_research=True, force_rebuild=False, research_update_id=None, analysis_report_id=None):
    from backend import evidence_packs
    if refresh_research and evidence_packs.source_fingerprints(company):
        await asyncio.to_thread(evidence_packs.refresh, company)
    # Every explicit valuation run attempts live research, including repeated
    # same-day runs. An unfinished or failed check is retained in the export.
    from backend import company_updates
    if refresh_research:
        await company_updates.for_valuation(company)
    package = company_package(company, update_run_id=research_update_id)
    if not refresh_research and not research_update_id:
        package['limitations'].append('Financial-statement integration rebuild only. Previously dated news is retained; no new online check was performed for this export.')
    if analysis_report_id:
        from backend import report_excel
        report_excel.attach(package,analysis_report_id)
    return await export_package(company,package,export_id,force_rebuild=force_rebuild,focused_previews=not refresh_research)


async def export_package(company,package,export_id=None,*,force_rebuild=False,focused_previews=True):
    """Build an exact input package, preserving previously reviewed assumptions."""
    if package.get('company_id')!=company:raise ValueError('Workbook input company mismatch.')
    package=json.loads(json.dumps(package))
    export_id = export_id or uuid4().hex
    fingerprint = input_fingerprint(package)
    cached = None if force_rebuild else cached_export(fingerprint)
    if cached:
        with storage.database() as db:
            db.execute('INSERT OR REPLACE INTO excel_exports(id,company,created_at,status,input_json,workbook_path) VALUES(?,?,?,?,?,?)',
                       (export_id, company, storage.now(), 'exported', json.dumps(package), cached['workbook_path']))
        return {'export_id': export_id, 'status': 'exported', 'cached': True, 'reused_from': cached['id'],
                'download_url': f'/excel/exports/{export_id}', 'data_issues': package['issues'], 'native_excel_verified': False}
    output_dir = storage.PROJECT_DIR / 'outputs' / export_id
    output_dir.mkdir(parents=True, exist_ok=False)
    source = output_dir / 'inputs.json'
    source.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding='utf-8')
    runtime = json.loads((storage.PROJECT_DIR / 'config/runtime.json').read_text())
    with storage.database() as db:
        db.execute('INSERT OR REPLACE INTO excel_exports(id,company,created_at,status,input_json) VALUES(?,?,?,?,?)',
                   (export_id, company, storage.now(), 'building', json.dumps(package)))
    process = await asyncio.create_subprocess_exec(runtime['node'], str(storage.PROJECT_DIR / 'excel/build.mjs'),
                  '--input', str(source), '--out', str(output_dir), *(['--focused-previews'] if focused_previews else []), cwd=str(storage.PROJECT_DIR),
                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 600)
        (output_dir / 'build.stdout.txt').write_bytes(stdout)
        (output_dir / 'build.stderr.txt').write_bytes(stderr)
        if process.returncode != 0:
            raise ValueError('Excel authoring failed. Check the local build verification file.')
        path = output_dir / 'SignalAI_FMCG_Valuation.xlsx'
        if not path.is_file():
            raise ValueError('Workbook export did not produce a file.')
        links=output_dir/'report-links.json'
        if links.is_file():
            from tools.add_report_links import apply
            await asyncio.to_thread(apply,path,links)
        status, error = 'exported', None
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
            await process.wait()
        with storage.database() as db:
            db.execute("UPDATE excel_exports SET status='interrupted',error='Workbook build cancelled during shutdown.' WHERE id=?", (export_id,))
        raise
    except Exception:
        if process.returncode is None:
            process.kill()
            await process.wait()
        status, error, path = 'failed', 'Workbook authoring or verification failed.', None
    with storage.database() as db:
        db.execute('UPDATE excel_exports SET status=?,workbook_path=?,error=? WHERE id=?',
                   (status, str(path) if path else None, error, export_id))
        if status == 'exported':
            db.execute('INSERT OR REPLACE INTO excel_export_cache VALUES(?,?,?)',
                       (fingerprint, export_id, digest_file(path)))
    return {'export_id': export_id, 'status': status, 'download_url': f'/excel/exports/{export_id}' if path else None,
            'cached': False, 'data_issues': package['issues'], 'native_excel_verified': False}
