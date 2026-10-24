"""Source-linked operating comparisons, separate from selected valuation peers.

No forecasts, market prices, multiples or valuation weights are manufactured.
This module owns source selection; business ratios are calculated in Excel.
"""
import json
from datetime import date
from backend import storage
from backend.discovery_view import safe_url


def build(subject, package_loader=None):
    from backend import excel_engine
    load = package_loader or (lambda company: excel_engine.company_package(company, include_comparison=False))
    path = storage.PROJECT_DIR / 'config/company_folders.json'
    cohort = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    rows = []
    for company in sorted(cohort):
        try:
            package = subject if company == subject['company_id'] else load(company)
        except (ValueError, OSError):
            continue
        periods = package.get('historical_statements', {}).get('periods', [])
        latest = package.get('periods', [None])[-1]
        # The forecast basis has already been selected and reconciled by intake.
        candidates = [p for p in periods if p['end'] == latest
                      and p.get('accounting_scope') == package.get('market', {}).get('accounting_scope')]
        if len(candidates) != 1:
            continue
        period = candidates[0]
        if not 330 <= period['duration_days'] <= 370:
            continue
        values, sources = {}, {}
        for metric in ('revenue', 'ebitda', 'net_income', 'cfo', 'capex', 'debt', 'cash'):
            refs = [r for r in period.get('sources', {}).get(metric, [])
                    if r.get('sha256') and safe_url(r.get('url'))]
            if refs and isinstance(period['values'].get(metric), (int, float)):
                values[metric] = period['values'][metric]
                sources[metric] = refs
        if 'revenue' not in values:
            continue
        previous = [p for p in periods if p['end'] < period['end']
                    and p.get('scope') == period.get('scope')
                    and abs(p['duration_days'] - period['duration_days']) <= 2
                    and abs((date.fromisoformat(period['end']) - date.fromisoformat(p['end'])).days - 365) <= 2]
        prior = previous[-1] if previous else None
        prior_refs = [r for r in (prior or {}).get('sources', {}).get('revenue', [])
                      if r.get('sha256') and safe_url(r.get('url'))]
        if prior and prior_refs and isinstance(prior['values'].get('revenue'), (int, float)):
            values['prior_revenue'] = prior['values']['revenue']
            sources['prior_revenue'] = prior_refs
        reason = ('Diversified group: tobacco, agri and paper distort a whole-company FMCG comparison. Use segment peers for valuation.'
                  if company == 'itc' else
                  'Operating benchmark only. Product/category mix, geography, scale, accounting definitions and one-off items need peer-selection review.')
        rows.append({'company_id': company, 'company': package['company'], 'subject': company == subject['company_id'],
                     'start': period['start'], 'end': period['end'], 'duration_days': period['duration_days'],
                     'scope': period['scope'], 'values': values, 'sources': sources,
                     'prior_end': prior['end'] if 'prior_revenue' in values else None,
                     'valuation_peer_approved': False, 'reason': reason,
                     'verification': 'Reviewed input records and source-file integrity; issuer authenticity and earnings normalisation not independently established.'})
    return {'rows': rows, 'checked_at': storage.now(),
            'status': 'Operating benchmarks; valuation peer selection incomplete',
            'limitations': ['These are reported group figures, not normalised peer earnings.',
                           'Same annual ending date does not make different product mixes or operating scopes equivalent.',
                           'No peer multiple, target multiple or reconciliation weight is inferred from these operating benchmarks.',
                           'Matched-date verifiable prices, share counts, enterprise-value bridges and category/segment review are required for valuation peers.']}
