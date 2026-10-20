"""Run offline engineering checks and save auditable results. Never call a real model."""
import json
import sys
import unittest
from backend import storage


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({'name': test.id(), 'passed': True})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({'name': test.id(), 'passed': False})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({'name': test.id(), 'passed': False})


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(storage.PROJECT_DIR / 'tests'))
    result = unittest.TextTestRunner(verbosity=1, resultclass=RecordedResult).run(suite)
    storage.initialize()
    summary = {'created_at': storage.now(), 'tests': result.testsRun,
               'failures': len(result.failures), 'errors': len(result.errors),
               'passed': result.wasSuccessful(), 'external_model_calls': 0,
               'financial_release_approval': False, 'cases': result.records}
    with storage.database() as db:
        for record in result.records:
            db.execute('INSERT INTO evaluation_cases(name,expected_json,observed_json,passed) VALUES(?,?,?,?)',
                       (record['name'], json.dumps({'expected': 'offline fixture passes'}),
                        json.dumps({'passed': record['passed'], 'checked_at': summary['created_at']}), int(record['passed'])))
    path = storage.PROJECT_DIR / 'reports' / 'engineering-evaluation.json'
    path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'cases'}, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
