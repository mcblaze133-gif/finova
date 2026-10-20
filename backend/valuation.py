"""Scenario valuation, never live prices or investment recommendations."""
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.facts import decimal

METHODS = ['Market snapshot', 'P/E and earnings yield', 'EV/EBITDA and EV/EBIT',
           'P/S and EV/Sales', 'P/B and tangible book', 'FCF and dividend yield',
           'Peer and historical multiples', 'FCFF DCF', 'Reverse DCF', 'FCFE',
           'Dividend discount', 'Sum of the parts', 'Residual income / economic profit',
           'PEG', 'Asset / liquidation value', 'Precedent transactions / real options']


class Scenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['bear', 'base', 'bull']
    revenue: str
    growth: str
    margin: str
    tax_rate: str
    da_ratio: str
    capex_ratio: str
    working_capital_ratio: str
    wacc: str
    terminal_growth: str
    terminal_roic: str
    debt: str
    cash: str
    minorities: str = '0'
    preferred: str = '0'
    nonoperating_assets: str = '0'
    shares: str
    years: int = Field(default=5, ge=1, le=10)
    currency: Literal['INR'] = 'INR'
    accounting_scope: Literal['consolidated', 'standalone']
    lease_policy: str = Field(min_length=10, max_length=600)
    rationale: str = Field(min_length=20, max_length=2000)
    # Amounts use plain INR and actual shares, never crore amounts / crore shares.
    @model_validator(mode='after')
    def valid(self):
        numeric = ('revenue', 'growth', 'margin', 'tax_rate', 'da_ratio', 'capex_ratio',
                   'working_capital_ratio', 'wacc', 'terminal_growth', 'terminal_roic',
                   'debt', 'cash', 'minorities', 'preferred', 'nonoperating_assets', 'shares')
        values = {key: decimal(getattr(self, key)) for key in numeric}
        if values['revenue'] <= 0 or values['shares'] <= 0:
            raise ValueError('Revenue and shares must be positive.')
        for key in ('tax_rate', 'da_ratio', 'capex_ratio', 'working_capital_ratio'):
            if not 0 <= values[key] <= 1:
                raise ValueError(f'{key} must be a fraction between zero and one.')
        if not -1 < values['growth'] <= 1 or not -1 <= values['margin'] <= 1:
            raise ValueError('Growth or margin is outside supported scenario bounds.')
        if not 0 < values['wacc'] <= 1 or not 0 <= values['terminal_growth'] < values['wacc']:
            raise ValueError('Require positive WACC greater than nonnegative terminal growth.')
        if not values['terminal_growth'] < values['terminal_roic'] <= 1:
            raise ValueError('Terminal ROIC must exceed terminal growth and be at most one.')
        for key in ('debt', 'cash', 'minorities', 'preferred', 'nonoperating_assets'):
            if values[key] < 0:
                raise ValueError(f'{key} cannot be negative.')
        return self


def dcf(scenario: Scenario):
    s = {k: decimal(v) for k, v in scenario.model_dump().items()
         if k in ('revenue', 'growth', 'margin', 'tax_rate', 'da_ratio', 'capex_ratio',
                  'working_capital_ratio', 'wacc', 'terminal_growth', 'terminal_roic',
                  'debt', 'cash', 'minorities', 'preferred', 'nonoperating_assets', 'shares')}
    revenue, present, rows = s['revenue'], Decimal(0), []
    for year in range(1, scenario.years + 1):
        prior = revenue
        revenue *= 1 + s['growth']
        ebit = revenue * s['margin']
        nopat = ebit * (1 - s['tax_rate'])
        da, capex = revenue * s['da_ratio'], revenue * s['capex_ratio']
        delta_wc = (revenue - prior) * s['working_capital_ratio']
        fcff = nopat + da - capex - delta_wc
        pv = fcff / (1 + s['wacc']) ** year
        present += pv
        rows.append({k: str(v) for k, v in {'year': year, 'revenue': revenue, 'ebit': ebit,
                    'nopat': nopat, 'da': da, 'capex': capex, 'delta_wc': delta_wc, 'fcff': fcff, 'pv': pv}.items()})
    # Sustainable terminal growth requires reinvestment g / ROIC.
    terminal_nopat = revenue * (1 + s['terminal_growth']) * s['margin'] * (1 - s['tax_rate'])
    terminal_fcff = terminal_nopat * (1 - s['terminal_growth'] / s['terminal_roic'])
    if terminal_fcff <= 0:
        raise ValueError('Stable positive terminal cash flow cannot be established.')
    terminal_value = terminal_fcff / (s['wacc'] - s['terminal_growth'])
    terminal_pv = terminal_value / (1 + s['wacc']) ** scenario.years
    ev = present + terminal_pv
    equity = ev + s['cash'] + s['nonoperating_assets'] - s['debt'] - s['minorities'] - s['preferred']
    return {'status': 'scenario only', 'currency': 'INR', 'amount_basis': 'plain INR; actual shares',
            'formula_version': 'fcff-v1', 'scenario': scenario.name, 'forecast': rows,
            'enterprise_value': str(ev), 'equity_value': str(equity), 'per_share': str(equity / s['shares']),
            'terminal_fcff': str(terminal_fcff), 'terminal_pv': str(terminal_pv),
            'terminal_share_of_ev': str(terminal_pv / ev) if ev else None,
            'assumptions': scenario.model_dump(),
            'warning': 'User-supplied assumptions; not independently validated financial facts. No investment recommendation.'}


def sensitivity(scenario):
    grid = []
    for wacc in (decimal(scenario.wacc) - Decimal('.01'), decimal(scenario.wacc), decimal(scenario.wacc) + Decimal('.01')):
        for growth in (decimal(scenario.terminal_growth) - Decimal('.005'), decimal(scenario.terminal_growth), decimal(scenario.terminal_growth) + Decimal('.005')):
            try:
                candidate = Scenario.model_validate({**scenario.model_dump(), 'wacc': str(wacc), 'terminal_growth': str(growth)})
                grid.append({'wacc': str(wacc), 'terminal_growth': str(growth), 'per_share': dcf(candidate)['per_share']})
            except ValueError:
                grid.append({'wacc': str(wacc), 'terminal_growth': str(growth), 'status': 'invalid assumptions'})
    return grid


def reverse_dcf(scenario, target_ev, lower='-0.20', upper='0.50'):
    target = decimal(target_ev)
    low, high = decimal(lower), decimal(upper)
    if target <= 0 or not Decimal('-1') < low < high <= 1:
        raise ValueError('Invalid market enterprise value or search bounds.')
    def value(growth):
        candidate = Scenario.model_validate({**scenario.model_dump(), 'growth': str(growth)})
        return decimal(dcf(candidate)['enterprise_value'])
    left, right = value(low), value(high)
    if not left <= target <= right or left >= right:
        return {'status': 'insufficient data', 'reason': 'No feasible monotonic solution inside search bounds.', 'bounds': [str(low), str(high)]}
    for _ in range(100):
        mid = (low + high) / 2
        if value(mid) < target:
            low = mid
        else:
            high = mid
    return {'status': 'scenario only', 'implied_revenue_growth': str((low + high) / 2),
            'search_bounds': [lower, upper], 'target_enterprise_value': str(target),
            'fixed_assumptions': scenario.model_dump(), 'limitation': 'Target is an explicit scenario input unless backed by a dated validated market snapshot.'}


def multiples(values):
    v = {key: decimal(value) for key, value in values.items()}
    required = ('price', 'shares', 'debt', 'cash', 'minorities', 'preferred')
    if not all(k in v for k in required):
        raise ValueError('Explicit price, shares, debt, cash, minorities and preferred are required.')
    if v['price'] <= 0 or v['shares'] <= 0 or any(v[k] < 0 for k in ('debt', 'cash', 'minorities', 'preferred')):
        raise ValueError('Invalid market snapshot amounts.')
    equity = v['price'] * v['shares']
    ev = equity + v['debt'] + v['minorities'] + v['preferred'] - v['cash']
    output = {'equity_value': str(equity), 'enterprise_value': str(ev), 'status': 'scenario only'}
    for label, denominator, numerator in (('pe', 'earnings', equity), ('ev_ebitda', 'ebitda', ev),
                                        ('ev_ebit', 'ebit', ev), ('ps', 'revenue', equity),
                                        ('ev_sales', 'revenue', ev), ('pb', 'book_equity', equity),
                                        ('p_tangible_book', 'tangible_equity', equity)):
        output[label] = str(numerator / v[denominator]) if denominator in v and v[denominator] > Decimal('0.000001') and numerator > 0 else None
    for label, amount, denominator in (('earnings_yield', 'earnings', equity), ('fcfe_yield', 'fcfe', equity),
                                       ('fcff_yield', 'fcff', ev), ('dividend_yield', 'dividends', equity)):
        output[label] = str(v[amount] / denominator) if amount in v and denominator > 0 else None
    output['limitation'] = 'Missing/nonmeaningful multiples are null. Inputs must share currency, scope, amount basis, lease policy and matching observation dates.'
    return output


def method_register():
    return [{'method': name, 'status': 'insufficient data',
             'reason': 'Validated dated financial and/or market inputs are unavailable; no result inferred from model memory.'}
            for name in METHODS]
