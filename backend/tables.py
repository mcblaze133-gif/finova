"""Conservative comparative-table parser for one explicit, testable layout.

Accepts only quarterly pages whose first two columns are current/prior years,
whose row contains four amounts, and whose scope is explicit. Other layouts
remain unparsed. No company-specific figures or conclusions live here.
"""
import calendar
import hashlib
import json
import re
from datetime import date
from backend import storage
from backend.facts import decimal

VERSION = 'quarter-table-v1'
NUMBER = r'(?<![\w.])\(?-?\d[\d,]*(?:\.\d+)?\)?(?![\w.])'
LABELS = {
    'total_income': r'\bTOTAL\s+INCOME\b',
    'profit': r'\bPROFIT\s+FOR\s+THE\s+PERIOD\s*/\s*YEAR\s+FROM\s+CONTINUING\s+OPERATIONS\s*\(A\)',
    'revenue': r'\bREVENUE\s+FROM\s+OPERATIONS\b',
}


def parse_quarter_table(text):
    scopes = re.findall(r'(?<![A-Z])(CONSOLIDATED|STANDALONE)\s+FINANCIAL\s+RESULTS', text, re.I)
    if len(set(s.casefold() for s in scopes)) != 1:
        return []
    header = re.search(r'FINANCIAL\s+RESULTS\s+FOR\s+THE\s+QUARTER\s+ENDED\s+(\d{1,2})(?:ST|ND|RD|TH)?\s+([A-Z]+)\s*,?\s*(20\d{2})', text, re.I)
    if not header or not re.search(r'\b(?:Rs\.?|INR)\s+in\s+crores\b', text, re.I):
        return []
    months = {m.casefold(): i for i, m in enumerate(calendar.month_name) if m}
    month = months.get(header[2].casefold())
    if month not in (3, 6, 9, 12):
        return []
    try:
        end = date(int(header[3]), month, int(header[1]))
    except ValueError:
        return []
    if end.day != calendar.monthrange(end.year, month)[1]:
        return []
    # Require the source itself to show the comparative year pair, in order.
    header_area = text[header.end():]
    first_body = re.search(r'CONTINUING\s+OPERATIONS|REVENUE\s+FROM\s+OPERATIONS', header_area, re.I)
    if not first_body:
        return []
    years_area = header_area[:first_body.start()]
    year_line = next((line for line in years_area.splitlines()
                      if re.findall(r'\b20\d{2}\b', line)[:2] == [str(end.year), str(end.year - 1)]), None)
    if year_line is None:
        return []
    output = []
    for metric, pattern in LABELS.items():
        matching = [line for line in text.splitlines() if re.search(pattern, line, re.I)]
        if len(matching) != 1:
            continue
        line = matching[0]
        label = re.search(pattern, line, re.I)
        tokens = re.findall(NUMBER, line[:label.start()] + ' ' + line[label.end():])
        if len(tokens) != 4:
            continue
        # This layout has two amounts to the left of Particulars and two to the
        # right. Never assume the position from the number of values alone.
        if len(re.findall(NUMBER, line[:label.start()])) != 2 or len(re.findall(NUMBER, line[label.end():])) != 2:
            continue
        for index, year in enumerate((end.year, end.year - 1)):
            value = tokens[index].replace(',', '')
            if value.startswith('(') and value.endswith(')'):
                value = '-' + value[1:-1]
            value = str(decimal(value))
            scope = 'continuing' if metric == 'profit' or 'CONTINUING OPERATIONS' in ' '.join(text[:text.index(line)].upper().split()) else 'total'
            output.append({'metric': metric, 'value_decimal': value, 'unit': 'INR_crore', 'currency': 'INR',
                           'period_start': date(year, month - 2, 1).isoformat(),
                           'period_end': date(year, month, end.day).isoformat(),
                           'accounting_scope': scopes[0].casefold(), 'operations_scope': scope,
                           'definition': ' '.join(label[0].casefold().split()), 'source_quote': line.strip(),
                           'proof': {'version': VERSION, 'header_quote': header[0], 'year_columns_quote': year_line.strip(),
                                     'column_index': index, 'column_layout': 'current/prior | Particulars | previous quarter/full year',
                                     'unit': 'Rs in crores', 'period_start_basis': 'Calendar three-month quarter inferred from explicit quarter-ended label.'}})
    return output


def extract_company(company, passage_ids):
    count = 0
    for passage_id in passage_ids:
        found = storage.rows('SELECT p.* FROM passages p JOIN documents d ON d.id=p.document_id WHERE p.id=? AND d.company=?', (passage_id, company))
        if not found:
            continue
        for fact in parse_quarter_table(found[0]['text']):
            fingerprint = hashlib.sha256(json.dumps({'passage_id': passage_id, **fact}, sort_keys=True).encode()).hexdigest()
            with storage.database() as db:
                if db.execute('SELECT 1 FROM fact_checks WHERE fingerprint=?', (fingerprint,)).fetchone():
                    continue
                columns = ('metric', 'value_decimal', 'unit', 'currency', 'period_start', 'period_end', 'accounting_scope', 'operations_scope', 'definition', 'source_quote')
                cursor = db.execute('INSERT INTO facts(passage_id,' + ','.join(columns) + ',validation_status) VALUES(' + ','.join('?' for _ in range(12)) + ')',
                                    [passage_id, *[fact[k] for k in columns], 'validated'])
                db.execute('INSERT INTO fact_checks VALUES(?,?,?,?)', (cursor.lastrowid, json.dumps(fact['proof']), fingerprint, VERSION))
                count += 1
    return count
