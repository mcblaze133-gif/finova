import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import storage, library, assumptions, excel_engine
from backend.valuation_spec import Assumption, FinancialRecord


class ExcelEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dbpatch = patch.object(storage, 'DB_PATH', self.root / 'test.sqlite')
        self.folderpatch = patch.object(library, 'root_folder', return_value=self.root)
        self.dbpatch.start(); self.folderpatch.start()
        with storage.database() as db:
            db.executescript(storage.SCHEMA)
            for name in ('002_research.sql','003_excel_engine.sql'):
                db.executescript((storage.PROJECT_DIR / 'schemas' / name).read_text())
        self.projectpatch=patch.object(storage,'PROJECT_DIR',self.root)
        self.projectpatch.start()
        (self.root / 'source.pdf').write_bytes(b'%PDF-fixture-source-reference-only')

    def tearDown(self):
        self.projectpatch.stop(); self.folderpatch.stop(); self.dbpatch.stop(); self.tmp.cleanup()

    def record(self, **changes):
        return FinancialRecord.model_validate({'company':'hul','metric':'revenue','value':'100',
            'unit':'INR_crore','currency':'INR','period_start':'2025-04-01','period_end':'2026-03-31',
            'accounting_scope':'consolidated','operations_scope':'continuing','segment':'group',
            'definition':'Revenue from operations','source_type':'historical','source_url':'https://example.org/report.pdf',
            'source_file':'source.pdf','source_page':'10','source_date':'2026-04-20','review_status':'user_verified',**changes})

    def write_csv(self, records):
        target = self.root/'financials.csv'
        with target.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0].model_dump()))
            writer.writeheader()
            writer.writerows(r.model_dump(mode='json') for r in records)
        return library.import_csv('financials.csv')

    def assumption(self, **changes):
        return Assumption.model_validate({'company':'hul','driver':'volume_growth','scenario':'base',
            'values':['.03']*5,'source_type':'analyst_assumption','source':'Analyst input',
            'source_date':'2026-10-18','confidence':'low','rationale':'Synthetic analyst test fixture only.',
            'derivation':'Explicit analyst estimate','override':True,**changes})

    def test_csv_amounts_converted_once_and_sources_preserved(self):
        result=self.write_csv([self.record()])
        self.assertEqual(result['status'],'imported')
        package=excel_engine.company_package('hul')
        self.assertEqual(package['financials']['revenue'][-1],1000000000)
        self.assertEqual(package['sources'][0]['source_page'],'10')
        self.assertEqual(package['market'],{})

    def test_selected_forecast_basis_keeps_other_scope_in_history(self):
        old=self.record(value='80',period_start='2023-04-01',period_end='2024-03-31',operations_scope='total')
        self.write_csv([self.record(),old])
        folder=self.root/'config/company_cases';folder.mkdir(parents=True)
        (folder/'hul.json').write_text(json.dumps({'historical_model_basis':['consolidated','continuing']}))
        package=excel_engine.company_package('hul')
        self.assertEqual(package['periods'],[None,None,None,None,'2026-03-31'])
        self.assertEqual(package['financials']['revenue'][-1],1000000000)
        self.assertEqual(len(package['historical_statements']['periods']),2)
        self.assertEqual(package['historical_statements']['periods'][0]['operations_scope'],'total')

    def test_duplicate_csv_reports_zero_new_records(self):
        self.assertEqual(self.write_csv([self.record()])['imported'],1)
        result = library.import_csv('financials.csv')
        self.assertEqual(result['records_checked'],1)
        self.assertEqual(result['imported'],0)

    def test_pending_inputs_and_estimates_cannot_become_historical_actuals(self):
        self.write_csv([self.record(review_status='pending'),self.record(metric='ebitda',source_type='analyst_assumption')])
        package=excel_engine.company_package('hul')
        self.assertTrue(all(v is None for v in package['financials']['revenue']))

    def test_conflicting_reviewed_records_not_silently_selected(self):
        self.write_csv([self.record(),self.record(value='120')])
        package=excel_engine.company_package('hul')
        self.assertIsNone(package['financials']['revenue'][-1])
        self.assertTrue(any('Conflicting' in issue for issue in package['issues']))

    def test_mixed_scopes_block_financial_build(self):
        self.write_csv([self.record(),self.record(metric='ebitda',accounting_scope='standalone')])
        package=excel_engine.company_package('hul')
        self.assertTrue(any('Mixed' in issue for issue in package['issues']))
        self.assertEqual(package['sources'],[])

    def test_intake_paths_cannot_escape_library(self):
        with self.assertRaises(ValueError): library.import_csv('../outside.csv')
        with self.assertRaises(ValueError): library.import_pdf('hul','../outside.pdf','https://example.org/file')

    def test_missing_source_file_rejects_whole_csv(self):
        result=self.write_csv([self.record(),self.record(metric='ebitda',source_file='missing.pdf')])
        self.assertEqual(result['status'],'rejected')
        self.assertEqual(library.company_records('hul'),[])

    def test_manual_override_survives_refresh(self):
        first=assumptions.save(self.assumption())
        with self.assertRaises(ValueError): assumptions.save(self.assumption(override=False))
        self.assertEqual(assumptions.list_for('hul')[0]['revision'],1)
        self.assertEqual(first['record']['source_type'],'analyst_assumption')

    def test_zero_assumption_is_preserved_and_audited(self):
        record=assumptions.save(self.assumption(driver='net_borrowing',values=['0']*5))
        self.assertEqual(record['record']['values'],['0']*5)
        self.assertEqual(len(storage.rows('SELECT * FROM assumption_changes')),1)

    def test_instruction_preview_does_not_apply_an_edit(self):
        result=assumptions.preview_change('hul','set base volume_growth to 5% for years 1-3')
        self.assertEqual(result['values'],['0.05','0.05','0.05',None,None])
        self.assertEqual(assumptions.list_for('hul'),[])
        with self.assertRaises(ValueError): assumptions.preview_change('hul','make growth better')

    def test_method_names_are_not_substituted_for_a_suitability_decision(self):
        package=excel_engine.company_package('hul')
        self.assertTrue(all(m['applicable']=='Conditional' for m in package['methods']))
        self.assertTrue(all(m['weight'] is None for m in package['methods']))

    def test_internal_source_review_requires_hash_quote_and_explanation(self):
        with self.assertRaises(ValueError):
            self.record(review_status='source_verified')

    def test_source_review_does_not_claim_user_verification(self):
        import hashlib
        digest=hashlib.sha256((self.root/'source.pdf').read_bytes()).hexdigest()
        record=self.record(review_status='source_verified',source_sha256=digest,
                           source_quote='Reported revenue is 100 crore.',review_note='SignalAI source-table review.')
        result=self.write_csv([record])
        self.assertEqual(result['status'],'imported')
        self.assertEqual(library.company_records('hul')[0].review_status,'source_verified')
        self.assertEqual(excel_engine.company_package('hul')['financials']['revenue'][-1],1e9)

    def test_changed_source_rejects_reviewed_csv(self):
        record=self.record(review_status='source_verified',source_sha256='a'*64,
                           source_quote='Reported revenue is 100 crore.',review_note='Source hash fixture intentionally mismatches.')
        self.assertEqual(self.write_csv([record])['status'],'rejected')

if __name__=='__main__': unittest.main()
