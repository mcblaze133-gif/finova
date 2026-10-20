import json
from uuid import uuid4
from backend import storage
from backend.valuation_spec import Assumption, DRIVERS


def save(assumption: Assumption, reason='Analyst supplied assumption', replace_override=False):
    with storage.database() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM driver_assumptions WHERE company=? AND driver=? AND scenario=?',
                         (assumption.company, assumption.driver, assumption.scenario)).fetchone()
        if old and json.loads(old['record_json']).get('override') and not replace_override:
            raise ValueError('An explicit manual override exists. Refresh cannot overwrite it.')
        assumption_id = old['id'] if old else uuid4().hex
        revision = old['revision'] + 1 if old else 1
        payload = assumption.model_dump_json()
        db.execute('INSERT INTO driver_assumptions VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET record_json=excluded.record_json,revision=excluded.revision,updated_at=excluded.updated_at',
                   (assumption_id, assumption.company, assumption.driver, assumption.scenario, payload, revision, storage.now()))
        db.execute('INSERT INTO assumption_changes(assumption_id,previous_json,next_json,reason,created_at) VALUES(?,?,?,?,?)',
                   (assumption_id, old['record_json'] if old else None, payload, reason, storage.now()))
    return {'id': assumption_id, 'revision': revision, 'record': assumption.model_dump(mode='json')}


def list_for(company):
    return [dict(row) | {'record': json.loads(row['record_json'])} for row in storage.rows(
        'SELECT * FROM driver_assumptions WHERE company=? ORDER BY driver,scenario', (company,))]


def preview_change(company, text):
    """Bounded change syntax, never guessed driver/case/value from vague prose."""
    import re
    match = re.fullmatch(r'set\s+(bear|base|bull)\s+([a-z_]+)\s+to\s+(-?\d+(?:\.\d+)?)(%?)\s+for\s+years\s+([1-5])-([1-5])', text.strip(), re.I)
    if not match:
        raise ValueError('Use: set base volume_growth to 5% for years 1-3. Ambiguous instructions are not applied.')
    scenario, driver, amount, percent, first, last = match.groups()
    scenario, driver = scenario.lower(), driver.lower()
    if driver not in DRIVERS or int(first) > int(last):
        raise ValueError('Unknown driver or invalid year range.')
    if percent and DRIVERS[driver][1] != 'fraction':
        raise ValueError('Percent input is only valid for fraction drivers.')
    from decimal import Decimal
    number = Decimal(amount) / (100 if percent else 1)
    old = next((r['record'] for r in list_for(company) if r['driver'] == driver and r['scenario'] == scenario), None)
    values = old['values'][:] if old else [None] * 5
    for year in range(int(first), int(last) + 1):
        values[year - 1] = str(number)
    return {'company': company, 'driver': driver, 'scenario': scenario, 'values': values,
            'source_type': 'analyst_assumption', 'override': True,
            'note': 'Preview only. Save with a source date, confidence, derivation and rationale. Existing Excel files are not modified by this preview.'}
