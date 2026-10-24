import hashlib
import json
import unittest
from pathlib import Path
from backend import storage,sector_status
from test_backend_audit import AuditFixture


class CoverageTests(AuditFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        (self.root/'config').mkdir()
        (self.root/'config/sector_universe.json').write_text(json.dumps({'companies':[{'id':'hul','role':'Reference constituent'}]}))
        self.book=self.root/'book.xlsx';self.book.write_bytes(b'fixture-workbook')
        self.pdf=self.root/'report.pdf';self.pdf.write_bytes(b'%PDF-fixture')
        self.rid='a'*32
        self.payload={'company_id':'hul','report_id':self.rid,'history':{},'research_excel_linked':True,
                      'workbook_sha256':hashlib.sha256(self.book.read_bytes()).hexdigest(),
                      'research':{'candidate_discovery':{'text':'A bounded hypothesis.',
                          'citations':[{'passage_id':1,'quote':'Exact company disclosure.'}]},
                          'passages':[{'id':1,'document_id':1,'pdf_page':2,'text':'Exact company disclosure.'}]}}
        with storage.database() as db:
            db.execute("INSERT INTO excel_exports(id,company,created_at,status,input_json,workbook_path) VALUES('export','hul',?,'exported','{}',?)",(storage.now(),str(self.book)))
            db.execute("INSERT INTO analysis_reports(id,company,created_at,updated_at,status,stage,export_id,pdf_path,snapshot_json) VALUES(?,'hul',?,?,'partial','finished','export',?,?)",(self.rid,storage.now(),storage.now(),str(self.pdf),json.dumps(self.payload)))

    def test_artifact_integrity_does_not_become_independent_verification(self):
        result=sector_status.build();row=result['companies'][0]
        self.assertTrue(row['checks_passed']);self.assertEqual(row['verified_discoveries'],0)
        self.assertIn('do not establish',result['meaning'])

    def test_changed_workbook_fails_integrity(self):
        self.book.write_bytes(b'changed')
        row=sector_status.build()['companies'][0]
        self.assertFalse(row['checks_passed']);self.assertFalse(row['checks']['workbook_hash'])

    def test_cross_company_snapshot_is_rejected(self):
        self.payload['company_id']='itc'
        with storage.database() as db:db.execute('UPDATE analysis_reports SET snapshot_json=?',(json.dumps(self.payload),))
        self.assertFalse(sector_status.build()['companies'][0]['checks_passed'])

    def test_active_run_is_separate_from_dated_delivered_report(self):
        with storage.database() as db:db.execute("INSERT INTO analysis_reports(id,company,created_at,updated_at,status,stage) VALUES(?,'hul',?,?,'running','research')",('b'*32,storage.now(),storage.now()))
        row=sector_status.build()['companies'][0]
        self.assertEqual(row['active_report_id'],'b'*32)
        self.assertEqual(row['delivered_report_id'],self.rid)
