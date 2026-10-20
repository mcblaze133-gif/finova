"""Method and driver definitions, not universal FMCG estimates."""
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

SOURCE_TYPES = Literal['historical', 'external', 'management_guidance', 'analyst_assumption']
SCENARIOS = ('bear', 'base', 'bull')
METRICS = ['revenue', 'ebitda', 'da', 'ebit', 'net_income', 'cfo', 'capex', 'operating_nwc',
           'debt', 'cash', 'nci', 'preferred', 'nonoperating_assets', 'book_equity', 'shares',
           'dividends', 'interest', 'assets', 'liabilities', 'invested_capital']

# Values are never supplied here. Driver relevance is determined from disclosed
# business drivers and required modules in the company evidence package.
DRIVERS = {
 'volume_growth': ('Volume growth', 'fraction', 'operating'),
 'price_mix_growth': ('Price and mix growth', 'fraction', 'operating'),
 'direct_revenue_growth': ('Revenue growth from disclosed drivers', 'fraction', 'operating'),
 'gross_margin': ('Gross margin', 'fraction', 'operating'),
 'advertising_ratio': ('Advertising / revenue', 'fraction', 'operating'),
 'employee_ratio': ('Employee costs / revenue', 'fraction', 'operating'),
 'other_opex_ratio': ('Other operating costs / revenue', 'fraction', 'operating'),
 'ebitda_margin': ('EBITDA margin', 'fraction', 'operating'),
 'da_ratio': ('D&A / revenue', 'fraction', 'operating'),
 'tax_rate': ('Operating tax rate', 'fraction', 'tax'),
 'capex_ratio': ('Capex / revenue', 'fraction', 'capital'),
 'nwc_ratio': ('Operating NWC / revenue', 'fraction', 'capital'),
 'net_borrowing': ('Net borrowing', 'INR', 'financing'),
 'interest_rate': ('Borrowing rate on opening debt', 'fraction', 'financing'),
 'nonoperating_income': ('Non-operating income before tax', 'INR', 'financing'),
 'nci_profit': ('Profit attributable to minorities', 'INR', 'financing'),
 'shares_change': ('Net change in diluted shares', 'shares', 'financing'),
 'equity_proceeds': ('Net equity issuance / repurchases', 'INR', 'financing'),
 'other_equity_changes': ('Other changes in equity', 'INR', 'financing'),
 'dividend_payout': ('Dividend payout', 'fraction', 'dividend'),
 'risk_free_rate': ('Risk-free rate', 'fraction', 'capital_cost'),
 'beta': ('Levered equity beta', 'ratio', 'capital_cost'),
 'equity_risk_premium': ('Equity risk premium', 'fraction', 'capital_cost'),
 'pretax_cost_debt': ('Pre-tax cost of debt', 'fraction', 'capital_cost'),
 'debt_weight': ('Debt / market capital', 'fraction', 'capital_cost'),
 'terminal_growth': ('Terminal growth', 'fraction', 'terminal'),
 'terminal_roic': ('Terminal return on invested capital', 'fraction', 'terminal'),
 'terminal_roe': ('Terminal return on equity', 'fraction', 'terminal'),
 'selected_pe': ('Selected forward P/E', 'multiple', 'multiples'),
 'selected_ev_ebitda': ('Selected forward EV/EBITDA', 'multiple', 'multiples'),
 'selected_ev_ebit': ('Selected forward EV/EBIT', 'multiple', 'multiples'),
 'selected_ev_sales': ('Selected forward EV/Sales', 'multiple', 'multiples'),
 'selected_ps': ('Selected forward P/S', 'multiple', 'multiples'),
 'selected_peg': ('Selected PEG', 'ratio', 'multiples'),
 'eps_growth_horizon': ('EPS CAGR for matching PEG horizon', 'fraction', 'multiples'),
 'selected_pta_revenue': ('Selected transaction EV/Revenue', 'multiple', 'transactions'),
 'selected_pta_ebitda': ('Selected transaction EV/EBITDA', 'multiple', 'transactions'),
 'terminal_value_limit': ('Terminal PV / EV review threshold', 'fraction', 'review'),
 'method_divergence_limit': ('Method-range dispersion review threshold', 'fraction', 'review'),
}

METHODS = ['DCF FCFF', 'FCFE', 'Forward P/E', 'EV/EBITDA', 'EV/EBIT', 'EV/Sales',
           'P/S', 'PEG', 'Precedent EV/Revenue', 'Precedent EV/EBITDA', 'DDM',
           'Residual income', 'NAV', 'SOTP']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


def finite(value):
    number = Decimal(str(value))
    if not number.is_finite() or abs(number) > Decimal('1e24'):
        raise ValueError('A finite financial value is required.')
    return number


class FinancialRecord(Strict):
    company: str = Field(pattern=r'^[a-z0-9-]{2,60}$')
    metric: str = Field(min_length=2, max_length=100)
    value: str
    unit: Literal['INR', 'INR_lakh', 'INR_crore', 'shares', 'fraction', 'ratio', 'multiple']
    currency: Literal['INR'] = 'INR'
    period_start: date | None = None
    period_end: date
    accounting_scope: Literal['consolidated', 'standalone']
    operations_scope: Literal['continuing', 'total']
    segment: str = 'group'
    definition: str = Field(min_length=3, max_length=1000)
    source_type: SOURCE_TYPES
    source_url: str = Field(min_length=5, max_length=2048)
    source_file: str = Field(min_length=1, max_length=500)
    source_page: str = Field(min_length=1, max_length=40)
    source_date: date
    review_status: Literal['pending', 'user_verified', 'source_verified'] = 'pending'
    source_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    source_quote: str | None = Field(default=None, max_length=8000)
    review_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode='after')
    def valid(self):
        finite(self.value)
        if self.period_start and self.period_start > self.period_end:
            raise ValueError('Invalid financial period.')
        if self.review_status == 'source_verified' and not (self.source_sha256 and self.source_quote and self.review_note):
            raise ValueError('Source review needs the exact file hash, page evidence and review explanation.')
        return self


class Assumption(Strict):
    company: str = Field(pattern=r'^[a-z0-9-]{2,60}$')
    driver: str
    scenario: Literal['bear', 'base', 'bull']
    values: list[str | None] = Field(min_length=5, max_length=5)
    source_type: SOURCE_TYPES
    source: str = Field(min_length=3, max_length=2000)
    source_date: date
    confidence: Literal['high', 'medium', 'low', 'unassessed']
    rationale: str = Field(min_length=10, max_length=3000)
    derivation: str = Field(min_length=3, max_length=2000)
    override: bool = False

    @model_validator(mode='after')
    def valid(self):
        if self.driver not in DRIVERS:
            raise ValueError('Unknown supported driver; register a driver definition before using it.')
        for value in self.values:
            if value is None:
                continue
            number = finite(value)
            if self.driver in ('volume_growth', 'price_mix_growth', 'direct_revenue_growth', 'eps_growth_horizon') and number <= -1:
                raise ValueError('Growth must exceed -100%.')
            if self.driver in ('tax_rate', 'debt_weight', 'dividend_payout') and not 0 <= number <= 1:
                raise ValueError('Rate must be between zero and one.')
        if self.override and self.source_type != 'analyst_assumption':
            raise ValueError('A manual override must be labelled analyst_assumption.')
        return self
