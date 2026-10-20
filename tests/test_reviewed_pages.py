import hashlib
import unittest
from unittest.mock import patch
from pypdf import PdfWriter
from backend import storage,library,reviewed_pages
from backend.valuation_spec import FinancialRecord
from test_backend_audit import AuditFixture

class ReviewedPageTests(AuditFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.sources=self.root/'sources';self.sources.mkdir()
        self.archive=self.root/'data/raw';self.archive.mkdir(parents=True)
        self.source=self.sources/'table.pdf';writer=PdfWriter();writer.add_blank_page(width=200,height=300);writer.write(self.source)
        raw=self.source.read_bytes();self.digest=hashlib.sha256(raw).hexdigest();(self.archive/'table.pdf').write_bytes(raw)
        self.data_patch=patch.object(storage,'DATA_DIR',self.root/'data');self.data_patch.start()
        self.root_patch=patch.object(library,'root_folder',return_value=self.sources);self.root_patch.start()
        with storage.database() as db:
            self.doc=db.execute("INSERT INTO documents(company,title,original_url,retrieved_at,sha256,local_path) VALUES('hul','Scanned table','https://example.org/report.pdf',?,?,?)",(storage.now(),self.digest,'data/raw/table.pdf')).lastrowid
        self.record=FinancialRecord(company='hul',metric='revenue',value='100',unit='INR',period_end='2022-03-31',accounting_scope='consolidated',operations_scope='total',definition='Reported revenue',source_type='historical',source_url='https://example.org/report.pdf',source_file='table.pdf',source_page='1',source_date='2022-04-30',review_status='source_verified',source_sha256=self.digest,source_quote='Revenue 100',review_note='Previously reviewed source page.')

    def tearDown(self):
        self.root_patch.stop();self.data_patch.stop();super().tearDown()

    def test_missing_scanned_page_gets_explicit_index_without_changing_pdf(self):
        before=self.source.read_bytes()
        with patch.object(library,'company_records',return_value=[self.record]):
            added=reviewed_pages.ensure('hul');self.assertEqual(len(added),1)
            self.assertEqual(reviewed_pages.ensure('hul'),[])
        text=storage.rows('SELECT text FROM passages WHERE document_id=?',(self.doc,))[0]['text']
        self.assertIn('NOT OCR and NOT a verbatim',text);self.assertIn('Revenue 100',text)
        self.assertEqual(self.source.read_bytes(),before)

    def test_existing_extraction_never_overwritten(self):
        with storage.database() as db:db.execute('INSERT INTO passages(document_id,pdf_page,text) VALUES(?,1,?)',(self.doc,'Original extracted text'))
        with patch.object(library,'company_records',return_value=[self.record]):self.assertEqual(reviewed_pages.ensure('hul'),[])
        self.assertEqual(storage.rows('SELECT text FROM passages')[0]['text'],'Original extracted text')

    def test_corrected_reviewed_records_refresh_only_the_labelled_index(self):
        with patch.object(library,'company_records',return_value=[self.record]):reviewed_pages.ensure('hul')
        updated=self.record.model_copy(update={'value':'101','source_quote':'Revenue 101 (corrected reviewed record)'})
        with patch.object(library,'company_records',return_value=[updated]):self.assertEqual(len(reviewed_pages.ensure('hul')),1)
        text=storage.rows('SELECT text FROM passages')[0]['text']
        self.assertIn('Revenue 101',text);self.assertNotIn('Revenue 100',text)

    def test_stale_or_unreviewed_records_cannot_seed_a_page(self):
        with patch.object(library,'company_records',return_value=[self.record.model_copy(update={'review_status':'pending'})]):
            self.assertEqual(reviewed_pages.ensure('hul'),[])
        self.source.write_bytes(b'changed source')
        with patch.object(library,'company_records',return_value=[self.record]):self.assertEqual(reviewed_pages.ensure('hul'),[])
        self.assertFalse(storage.rows('SELECT * FROM passages'))

    def test_invalid_page_reference_rejected(self):
        with patch.object(library,'company_records',return_value=[self.record.model_copy(update={'source_page':'2'})]):
            with self.assertRaises(ValueError):reviewed_pages.ensure('hul')
