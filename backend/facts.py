"""Fail-closed numerical grounding. Ambiguous model output remains quarantined."""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend import storage

METRICS = {
    'revenue': ('revenue from operations', 'revenue from contracts', 'net sales'),
    'profit': ('profit for the year', 'profit for the period', 'profit after tax'),
    'operating_cash_flow': ('net cash from operating', 'net cash generated from operating'),
    'receivables': ('trade receivables',), 'inventory': ('inventories', 'inventory'),
    'payables': ('trade payables',), 'ebit': ('earnings before interest and tax',),
    'ebitda': ('ebitda',), 'cogs': ('cost of goods sold', 'cost of sales'),
    'volume_growth': ('volume growth', 'underlying volume growth'),
    'stores': ('number of stores', 'store count'),
}
UNITS = {'INR': ('rupees', 'inr', '₹', 'rs.'),
         'INR_lakh': ('lakh', 'lacs'), 'INR_crore': ('crore', 'cr.'),
         'percent': ('%', 'percent', 'per cent'), 'count': ('number', 'stores')}


def decimal(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Invalid decimal value.') from None
    if not number.is_finite() or abs(number) > Decimal('1e24'):
        raise ValueError('Nonfinite or excessive numeric value.')
    return number


def normalized(text):
    return ' '.join(text.casefold().split())


class Fact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    passage_id: int = Field(gt=0)
    metric: Literal['revenue', 'profit', 'operating_cash_flow', 'receivables', 'inventory', 'payables', 'ebit', 'ebitda', 'cogs', 'volume_growth', 'stores']
    value_decimal: str = Field(max_length=40)
    unit: Literal['INR', 'INR_lakh', 'INR_crore', 'percent', 'count']
    currency: Literal['INR'] | None = None
    period_start: date | None = None
    period_end: date
    accounting_scope: Literal['standalone', 'consolidated']
    operations_scope: Literal['continuing', 'total']
    definition: str = Field(min_length=3, max_length=500)
    source_quote: str = Field(min_length=5, max_length=4000)
    unit_quote: str = Field(min_length=1, max_length=200)
    period_quote: str = Field(min_length=4, max_length=300)
    scope_quote: str = Field(min_length=4, max_length=200)

    @model_validator(mode='after')
    def check(self):
        decimal(self.value_decimal)
        if self.period_start and self.period_start > self.period_end:
            raise ValueError('Period starts after period end.')
        if self.unit.startswith('INR') != (self.currency == 'INR'):
            raise ValueError('Unit and currency do not agree.')
        return self


def quote_dates(text):
    # Accept explicit source dates only. Fiscal-year shorthand is ambiguous.
    result = set()
    text = re.sub(r'\b(\d{1,2})(?:st|nd|rd|th)\b', r'\1', text, flags=re.I)
    text = re.sub(r'([A-Za-z]),\s*', r'\1 ', text)
    for pattern, fmt in ((r'\b\d{4}-\d{2}-\d{2}\b', '%Y-%m-%d'),
                         (r'\b\d{1,2}[./]\d{1,2}[./]\d{4}\b', '%d.%m.%Y'),
                         (r'\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b', '%d %B %Y')):
        for token in re.findall(pattern, text):
            try:
                result.add(__import__('datetime').datetime.strptime(token.replace('/', '.') if fmt == '%d.%m.%Y' else token, fmt).date())
            except ValueError:
                pass
    return result


def validate_fact(fact: Fact, company=None):
    passages = storage.rows('SELECT p.*,d.company FROM passages p JOIN documents d ON d.id=p.document_id WHERE p.id=?', (fact.passage_id,))
    if not passages or (company and passages[0]['company'] != company):
        raise ValueError('Fact passage is missing or belongs to another company.')
    passage = normalized(passages[0]['text'])
    quotes = (fact.source_quote, fact.unit_quote, fact.period_quote, fact.scope_quote)
    checks = {'quotes_present': all(normalized(q) in passage for q in quotes),
              'metric_label': any(label in normalized(fact.source_quote) for label in METRICS[fact.metric]),
              'unit_grounded': any(label in normalized(fact.unit_quote) for label in UNITS[fact.unit]),
              'scope_grounded': fact.accounting_scope in normalized(fact.scope_quote),
              'period_end_grounded': fact.period_end in quote_dates(fact.period_quote),
              'period_start_grounded': fact.period_start is None or fact.period_start in quote_dates(fact.period_quote)}
    tokens = re.findall(r'(?<![\w.])\(?-?\d[\d,]*(?:\.\d+)?\)?(?![\w.])', fact.source_quote)
    values = []
    for token in tokens:
        token = token.replace(',', '')
        if token.startswith('(') and token.endswith(')'):
            token = '-' + token[1:-1]
        try:
            values.append(decimal(token))
        except ValueError:
            pass
    checks['value_present'] = decimal(fact.value_decimal) in values
    # A quote with multiple numbers may be a multi-column financial table.
    # Without deterministic column mapping, it is not safe to select a period.
    checks['unambiguous_value'] = len(values) == 1
    matching_lines = [line for line in passages[0]['text'].splitlines() if normalized(fact.source_quote) in normalized(line)]
    checks['complete_numeric_row'] = bool(matching_lines) and all(len(re.findall(r'(?<![\w.])\(?-?\d[\d,]*(?:\.\d+)?\)?(?![\w.])', line)) == 1 for line in matching_lines)
    checks['scope_unambiguous'] = not ('standalone' in passage and 'consolidated' in passage)
    checks['unit_unambiguous'] = not (fact.unit == 'INR' and any(word in normalized(fact.unit_quote) for word in ('lakh', 'crore', 'lacs', 'cr.')))
    checks['metric_unit_consistent'] = fact.unit == ('percent' if fact.metric == 'volume_growth' else 'count' if fact.metric == 'stores' else fact.unit) and (fact.metric in ('volume_growth', 'stores') or fact.unit.startswith('INR'))
    checks['not_adjusted_metric'] = not any(word in normalized(fact.source_quote) for word in ('before exceptional', 'adjusted', 'excluding exceptional'))
    checks['operations_grounded'] = (fact.operations_scope == 'continuing' and 'continuing operations' in normalized(fact.source_quote)) or (fact.operations_scope == 'total' and any(word in normalized(fact.source_quote) for word in ('total operations', 'continuing and discontinued', 'including discontinued')))
    if fact.metric in ('revenue', 'profit', 'operating_cash_flow', 'cogs', 'ebit', 'ebitda', 'volume_growth'):
        checks['flow_period_known'] = fact.period_start is not None
    status = 'validated' if all(checks.values()) else 'pending'
    payload = fact.model_dump(mode='json')
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with storage.database() as db:
        existing = db.execute('SELECT fact_id FROM fact_checks WHERE fingerprint=?', (fingerprint,)).fetchone()
        if existing:
            return {'id': existing[0], 'validation_status': status, 'checks': checks}
        columns = ('passage_id', 'metric', 'value_decimal', 'unit', 'currency', 'period_start', 'period_end', 'accounting_scope', 'operations_scope', 'definition', 'source_quote')
        cursor = db.execute('INSERT INTO facts(' + ','.join(columns) + ',validation_status) VALUES(' + ','.join('?' for _ in range(12)) + ')',
                            [payload[k] for k in columns] + [status])
        fact_id = cursor.lastrowid
        db.execute('INSERT INTO fact_checks(fact_id,checks_json,fingerprint,version) VALUES(?,?,?,?)',
                   (fact_id, json.dumps(checks), fingerprint, 'grounding-v1'))
    return {'id': fact_id, 'validation_status': status, 'checks': checks}
