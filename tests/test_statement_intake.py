import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from backend import storage,library,statement_intake as intake,verification

TEXT='''Consolidated Statement of Profit and Loss
(INR in crores)
Particulars Year ended 31st March, 2026 Year ended 31st March, 2025
CONTINUING OPERATIONS
Revenue from operations 27  1,000  900
Depreciation and amortisation expense  10  9
Finance costs  2  3
'''


class StatementIntakeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.source=self.root/'source.pdf';self.source.write_bytes(b'%PDF-test-fixture')
        for p in [patch.object(storage,'DB_PATH',self.root/'local.sqlite'),patch.object(library,'root_folder',return_value=self.root)]:
            p.start();self.addCleanup(p.stop)
        with storage.database() as db:
            db.executescript(storage.SCHEMA)
            for schema in (storage.PROJECT_DIR/'schemas').glob('*.sql'):db.executescript(schema.read_text())
            doc=db.execute("INSERT INTO documents(company,title,original_url,retrieved_at,sha256,local_path) VALUES('demo','Test','https://example.com/source.pdf',?,?,?)",(storage.now(),hashlib.sha256(self.source.read_bytes()).hexdigest(),'fixture')).lastrowid
            db.execute('INSERT INTO passages(document_id,pdf_page,text) VALUES(?,1,?)',(doc,TEXT))
            db.execute("INSERT INTO library_documents(company,relative_path,document_id) VALUES('demo','source.pdf',?)",(doc,))

    def item(self):
        intake.scan('demo')
        return next(c for c in intake.candidates('demo') if c['metric']=='revenue' and c['period_end']=='2026-03-31')

    def approve(self,cid):
        return intake.review(cid,'approve','Checked source row, units, scope and annual periods.',source_date=date(2026,4,30),confirm_period=True)

    def test_extracts_source_values_dates_scope_and_units(self):
        rows,_=intake.parse_page(TEXT)
        self.assertEqual(len(rows),6)
        rev=rows[0]
        self.assertEqual((rev['value'],rev['period_start'],rev['period_end']),('1000','2025-04-01','2026-03-31'))
        self.assertEqual(rev['operations_scope'],'continuing')
        self.assertEqual(rev['currency'],'INR')
        self.assertIn('1,000',rev['source_quote'])

    def test_unsupported_headers_units_periods_and_note_tables_rejected(self):
        variants=[TEXT.replace('Consolidated Statement','Notes to the consolidated statement'),
                  TEXT.replace('(INR in crores)',''),TEXT.replace('2025','2024'),
                  TEXT.replace('Statement of Profit and Loss','Financial Results for the Quarter'),
                  TEXT+'\nFor the 15 months ended March 2026']
        for text in variants:self.assertEqual(intake.parse_page(text)[0],[],text)

    def test_ambiguous_currency_stays_unconfirmed(self):
        rows,_=intake.parse_page(TEXT.replace('INR','H'))
        self.assertIsNone(rows[0]['currency'])
        self.assertFalse(rows[0]['checks']['currency_explicit'])

    def test_duplicate_rows_and_discontinued_rows_not_silently_selected(self):
        rows,_=intake.parse_page(TEXT+'Revenue from operations  2,000  1,900\n')
        self.assertFalse(any(x['metric']=='revenue' for x in rows))
        rows,_=intake.parse_page(TEXT.replace('CONTINUING OPERATIONS','DISCONTINUED OPERATIONS'))
        self.assertEqual(rows,[])
        for value in ['(1,000','1,000)','(-1,000)']:
            rows,_=intake.parse_page(TEXT.replace('1,000',value))
            self.assertFalse(any(x['metric']=='revenue' for x in rows))

    def test_scans_incrementally_without_promoting_pending_values(self):
        first=intake.scan('demo');second=intake.scan('demo')
        self.assertEqual(first['candidates_added'],6)
        self.assertEqual(second['candidates_added'],0)
        self.assertEqual(second['unchanged_documents_skipped'],1)
        self.assertEqual(library.company_records('demo'),[])

    def test_approval_is_source_checked_reviewed_and_idempotent(self):
        candidate=self.item();result=self.approve(candidate['id'])
        self.assertEqual(result['status'],'approved')
        self.assertTrue(self.approve(candidate['id'])['already_reviewed'])
        records=library.company_records('demo');self.assertEqual(len(records),1)
        self.assertEqual(records[0].review_status,'user_verified')
        self.assertTrue(records[0].source_quote and records[0].review_note)

    def test_rejects_stale_sources_and_unconfirmed_periods(self):
        candidate=self.item()
        with self.assertRaisesRegex(ValueError,'reporting period'):
            intake.review(candidate['id'],'approve','Checked source amounts and units for this row.',source_date=date(2026,4,30))
        self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source changed'):self.approve(candidate['id'])
        intake.scan('demo')
        self.assertEqual(intake.candidates('demo')[0]['status'],'stale')

    def test_conflicting_reviewed_input_requires_reconciliation(self):
        candidate=self.item();self.approve(candidate['id'])
        with storage.database() as db:
            r=db.execute('SELECT * FROM library_records').fetchone();payload=json.loads(r['record_json']);payload['value']='999'
            db.execute('UPDATE library_records SET record_json=? WHERE id=?',(json.dumps(payload),r['id']))
            db.execute("UPDATE statement_candidates SET status='pending' WHERE id=?",(candidate['id'],))
        with self.assertRaisesRegex(ValueError,'Conflicts'):self.approve(candidate['id'])
        self.assertEqual(library.company_records('demo')[0].value,'999')

    def test_verification_does_not_claim_source_authenticity_or_pending_review(self):
        candidate=self.item();self.approve(candidate['id'])
        audit=verification.build('demo')
        self.assertEqual(audit['integrity_and_review_passed'],1)
        self.assertIn('not established',audit['systems'][1]['status'])
        self.source.write_bytes(b'changed')
        self.assertEqual(verification.build('demo')['integrity_and_review_passed'],0)

    def test_missing_review_explanation_and_bad_workbook_hash_are_visible(self):
        candidate=self.item();self.approve(candidate['id'])
        r=library.company_records('demo')[0].model_dump(mode='json');r['review_note']=None
        audit=verification.build('demo',{'sources':[r]},workbook_path=self.source,workbook_sha256='0'*64)
        self.assertEqual(audit['integrity_and_review_passed'],0)
        self.assertEqual(audit['systems'][4]['status'],'Workbook hash mismatch')

    def test_readable_verification_register_escapes_source_content(self):
        candidate=self.item();self.approve(candidate['id'])
        audit=verification.build('demo')
        audit['items'][0]['source']['quote']='<img src=x onerror=alert(1)>'
        audit['items'][0]['source']['url']='javascript:alert(1)'
        page=verification.render(audit,'<script>alert(1)</script>')
        self.assertNotIn('<script>',page);self.assertNotIn('<img',page)
        self.assertNotIn('href="javascript:',page);self.assertIn('&lt;img',page)
