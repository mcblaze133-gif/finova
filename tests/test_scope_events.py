import unittest
import hashlib
import json
from backend import scope_events as s
from backend import storage
from test_backend_audit import AuditFixture


EVENT={'label':'Reviewed demerger disclosure','observed_date':'2025-01-11','aliases':['Example Hotels'],
       'required_qualifiers':['associate','demerged','historical','no longer'],
       'passage':{'document_id':1,'pdf_page':3}}


class ScopeTests(unittest.TestCase):
    def test_unreconciled_subsidiary_claim_is_withheld(self):
        with self.assertRaisesRegex(ValueError,'reconciliation'):
            s.check('Subsidiaries including Example Hotels support growth.',[EVENT])
    def test_historical_or_associate_attribution_can_be_reviewed(self):
        s.check('Example Hotels is described as an associate in the filing.',[EVENT])
        s.check('Historical Example Hotels operations are shown separately.',[EVENT])
        s.check('Example Hotels was a subsidiary.',[EVENT],'2024-03-31')
    def test_unrelated_company_statement_is_preserved(self):
        s.check('Other subsidiaries recorded growth.',[EVENT])
    def test_suppression_revokes_admission_and_preserves_valid_statements(self):
        raw={'discovery':{'text':'Example Hotels is a subsidiary.'},'discovery_checks':{'admitted':True},
             'sector_sections':[{'topic':'Segments','statements':[{'text':'Example Hotels is a subsidiary.'},{'text':'The food business recorded growth.'}]}]}
        s.filter_research(raw,[EVENT])
        self.assertIsNone(raw['discovery']);self.assertFalse(raw['discovery_checks']['admitted'])
        self.assertEqual(len(raw['sector_sections'][0]['statements']),1)
        self.assertEqual(len(raw['scope_validation']['withheld']),2)
    def test_old_timeline_is_not_reinterpreted_as_current_ownership(self):
        raw={'timeline':[{'text':'Example Hotels was a subsidiary.','date':'2024-03-31'},
                         {'text':'Example Hotels is a subsidiary.','date':'2026-03-31'}]}
        s.filter_research(raw,[EVENT]);self.assertEqual(len(raw['timeline']),1)


class SourceIntegrityTests(AuditFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();(self.root/'data/raw').mkdir(parents=True)
        self.source=self.root/'data/raw/event.pdf';self.source.write_bytes(b'%PDF-fixture')
        digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        event=EVENT|{'company_id':'hul','passage_id':1,'source_sha256':digest,'quote':'The company disclosed an associate relationship.'}
        self.registry=self.root/'data/scope-events.json';self.registry.write_text(json.dumps([event]))
        with storage.database() as db:
            db.execute("INSERT INTO documents(id,company,title,original_url,retrieved_at,sha256,local_path) VALUES(1,'hul','Scope disclosure','https://example.test/source',?,?,?)",(storage.now(),digest,'data/raw/event.pdf'))
            db.execute("INSERT INTO passages(id,document_id,pdf_page,text) VALUES(1,1,3,'The company disclosed an associate relationship.')")
    def test_source_hash_and_exact_quote_required(self):
        self.assertEqual(len(s.load('hul')),1)
        self.source.write_bytes(b'changed')
        with self.assertRaises(s.ScopeEvidenceError):s.load('hul')
    def test_fabricated_quote_rejected(self):
        event=json.loads(self.registry.read_text())[0];event['quote']='Invented relationship.';self.registry.write_text(json.dumps([event]))
        with self.assertRaises(s.ScopeEvidenceError):s.load('hul')
    def test_corrupt_registry_does_not_disable_checks_silently(self):
        self.registry.write_text('{invalid')
        with self.assertRaises(s.ScopeEvidenceError):s.load('hul')
