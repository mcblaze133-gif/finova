"""Deterministic arithmetic over validated, comparable evidence only."""
import json
from datetime import date
from decimal import Decimal
from backend import storage
from backend.facts import decimal

VERSION = 'finance-v1'


def comparable(facts, across_periods=False):
    if any(f['validation_status'] != 'validated' for f in facts):
        raise ValueError('Only validated facts can enter calculations.')
    for key in ('company', 'unit', 'currency', 'accounting_scope', 'operations_scope'):
        if len({f[key] for f in facts}) != 1:
            raise ValueError(f'Incompatible {key}.')
    if across_periods:
        lengths = []
        for fact in facts:
            if not fact['period_start']:
                raise ValueError('Flow period start is required.')
            lengths.append((date.fromisoformat(fact['period_end']) - date.fromisoformat(fact['period_start'])).days)
        if max(lengths) - min(lengths) > 2:
            raise ValueError('Period lengths are incompatible.')
        if len({f['definition'].casefold() for f in facts}) != 1:
            raise ValueError('Metric definitions changed; cannot compare automatically.')
        ordered = sorted(facts, key=lambda f: f['period_end'])
        if ordered[0]['period_end'] >= ordered[-1]['period_start']:
            raise ValueError('Comparative periods overlap.')
        if len({f['period_end'][5:] for f in facts}) != 1:
            raise ValueError('Automatic growth compares matching year-on-year periods; seasonal quarter-on-quarter comparisons require separate review.')
    elif len({(f['period_start'], f['period_end']) for f in facts}) != 1:
        raise ValueError('Calculation requires matching periods.')


def calculate(formula, fact_ids, run_id=None):
    if len(fact_ids) != 2 or len(set(fact_ids)) != 2:
        raise ValueError('Exactly two distinct fact IDs are required.')
    facts = []
    for fact_id in fact_ids:
        rows = storage.rows('SELECT f.*,d.company,d.sha256 FROM facts f JOIN passages p ON p.id=f.passage_id JOIN documents d ON d.id=p.document_id WHERE f.id=?', (fact_id,))
        if not rows:
            raise ValueError('Input fact not found.')
        facts.append(rows[0])
    first, second = facts
    a, b = decimal(first['value_decimal']), decimal(second['value_decimal'])
    warnings = []
    if formula in ('revenue_growth', 'profit_growth', 'total_income_growth'):
        metric = {'revenue_growth': 'revenue', 'profit_growth': 'profit', 'total_income_growth': 'total_income'}[formula]
        if any(f['metric'] != metric for f in facts):
            raise ValueError('Growth requires matching metric facts.')
        comparable(facts, across_periods=True)
        if first['period_start'] <= second['period_end']:
            raise ValueError('Input order must be current revenue, prior revenue.')
        if b <= 0:
            raise ValueError('Prior revenue must be positive.')
        value, unit, expression = (a / b - 1) * 100, 'percent', '(current / prior - 1) * 100'
    elif formula in ('cash_conversion', 'ebit_margin', 'ebitda_margin'):
        expected = {'cash_conversion': ('operating_cash_flow', 'profit'), 'ebit_margin': ('ebit', 'revenue'), 'ebitda_margin': ('ebitda', 'revenue')}[formula]
        if (first['metric'], second['metric']) != expected:
            raise ValueError('Wrong metrics for formula.')
        comparable(facts)
        if b <= 0 or (formula == 'cash_conversion' and b < Decimal('0.000001')):
            raise ValueError('Denominator is nonpositive or near zero.')
        value, unit, expression = a / b, 'ratio', 'numerator / denominator'
        if formula != 'cash_conversion':
            value, unit, expression = value * 100, 'percent', '(operating earnings / revenue) * 100'
    else:
        raise ValueError('Unsupported formula.')
    output = {'formula': formula, 'expression': expression, 'value': str(value), 'unit': unit,
              'display_value': str(value.quantize(Decimal('0.0001'))), 'display_rounding': 'four decimal places; exact Decimal result retained in value',
              'input_fact_ids': fact_ids, 'inputs': facts, 'warnings': warnings,
              'comparability': 'Matched scope, units, currency, definitions and periods; source restatements still require review.',
              'formula_version': VERSION}
    with storage.database() as db:
        cursor = db.execute('INSERT INTO calculations(run_id,formula_version,formula,input_fact_ids,output_json,created_at) VALUES(?,?,?,?,?,?)',
                            (run_id, VERSION, formula, json.dumps(fact_ids), json.dumps(output), storage.now()))
        output['id'] = cursor.lastrowid
    return output


def price_mix(revenue_growth, volume_growth):
    revenue, volume = decimal(revenue_growth), decimal(volume_growth)
    if volume <= -1 or revenue <= -1:
        raise ValueError('Growth rates must exceed -100%.')
    return {'value': str((1 + revenue) / (1 + volume) - 1), 'unit': 'fraction',
            'limitation': 'Residual price/mix estimate, not pure pricing. Currency, acquisitions and scope must match.'}


def working_capital_days(opening, closing, flow, days):
    if not 1 <= days <= 550 or decimal(flow) <= 0:
        raise ValueError('A positive comparable flow and valid period length are required.')
    return str((decimal(opening) + decimal(closing)) / 2 / decimal(flow) * days)
