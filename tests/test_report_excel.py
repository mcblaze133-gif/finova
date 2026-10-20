import json,unittest
from unittest.mock import patch
from pathlib import Path
from backend import storage,report_excel,analysis_reports as ar
from test_backend_audit import AuditFixture

class ReportWorkbookTests(AuditFixture,unittest.TestCase):
 def setUp(self):
  super().setUp();self.rid='a'*32;self.run_row('research-fixture','2026-10-20T00:00:00+00:00')
  self.raw={'sector_sections':[{'topic':'Business and products','statements':[{'text':'Reported company portfolio.','citations':[{'passage_id':1,'quote':'Original company portfolio.'}]}],'investor_use':'Use the reported scope to choose suitable peers.','gaps':[]}],
   'passages':[{'id':1,'document_id':7,'pdf_page':3,'title':'Original financial disclosure'}],
   'section_analysis':{'finished_at':'2026-10-20T00:00:00Z','areas':[{'topic':'Business and products','status':'complete','review_reason':'Attributed source-backed description.'}]}}
  with storage.database() as db:
   db.execute('UPDATE research_runs SET report_json=? WHERE id=?',(json.dumps(self.raw),'research-fixture'))
   db.execute("INSERT INTO analysis_reports(id,company,created_at,updated_at,status,stage,research_run_id) VALUES(?,'hul',?,?,'running','valuation','research-fixture')",(self.rid,storage.now(),storage.now()))
 def package(self):return {'company_id':'hul','financials':{'revenue':[100]},'historical_statements':{},'research_notes':[]}
 def test_research_and_source_links_added_without_changing_financials(self):
  p=self.package();report_excel.attach(p,self.rid)
  self.assertEqual(p['financials'],{'revenue':[100]})
  self.assertEqual(p['research_report']['report_id'],self.rid)
  self.assertTrue(any('Reported company portfolio.'==n['finding'] for n in p['research_notes']))
  self.assertTrue(any(n.get('source_url','').endswith('/documents/7/original#page=3') for n in p['research_notes']))
  self.assertEqual(len(p['research_report']['research_sha256']),64)
 def test_wrong_company_is_rejected(self):
  p=self.package();p['company_id']='itc'
  with self.assertRaisesRegex(ValueError,'different company'):report_excel.attach(p,self.rid)
 def test_snapshot_rejects_workbook_for_different_report(self):
  with storage.database() as db:db.execute("INSERT INTO excel_exports(id,company,created_at,status,input_json,workbook_path) VALUES('export','hul',?,'exported',?,'fixture.xlsx')",(storage.now(),json.dumps({'research_report':{'report_id':'b'*32,'research_run_id':'research-fixture'}})))
  with patch.object(ar,'workbook_values',return_value={}):
   with self.assertRaisesRegex(ValueError,'different research report'):ar.snapshot('hul','research-fixture','export',self.rid)
 def test_snapshot_rejects_research_changed_after_excel_build(self):
  with storage.database() as db:db.execute("INSERT INTO excel_exports(id,company,created_at,status,input_json,workbook_path) VALUES('export','hul',?,'exported',?,'fixture.xlsx')",(storage.now(),json.dumps({'research_report':{'report_id':self.rid,'research_run_id':'research-fixture','research_sha256':'stale'}})))
  with patch.object(ar,'workbook_values',return_value={}):
   with self.assertRaisesRegex(ValueError,'changed after'):ar.snapshot('hul','research-fixture','export',self.rid)
