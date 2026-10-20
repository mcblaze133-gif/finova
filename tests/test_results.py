import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import storage, results, evidence_packs


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        project = storage.PROJECT_DIR
        self.patches = [patch.object(storage,'DB_PATH',self.root/'test.sqlite')]
        self.patches[0].start()
        with storage.database() as db:
            db.executescript(storage.SCHEMA)
            for path in (project/'schemas').glob('*.sql'):
                db.executescript(path.read_text())
        self.patches.append(patch.object(storage,'PROJECT_DIR',self.root))
        self.patches[-1].start()
        self.sources = self.root/'sources'
        self.sources.mkdir()
        self.patches.append(patch.object(results.library,'root_folder',return_value=self.sources))
        self.patches[-1].start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def export(self, path):
        with storage.database() as db:
            db.execute('INSERT INTO excel_exports VALUES(?,?,?,?,?,?,?)',
                ('fixture','hul',storage.now(),'exported',json.dumps({'methods':[{'method':'DCF FCFF','weight':1}]}),str(path),None))

    def test_results_use_saved_values_and_suppress_unavailable_methods(self):
        path = self.root/'outputs/case/report.xlsx'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'fixture - reader mocked')
        self.export(path)
        saved = {'Dashboard':{'C9':'DCF FCFF','D9':100,'E9':120,'F9':150,
                             'C10':'FCFE','D10':'n.a.','E10':None,'F10':'n.a.'},
                 'Market':{'D7':200,'D6':'2026-10-16T00:00:00.000Z','D22':'2026-10-18T00:00:00.000Z'}}
        with patch.object(results,'read_saved_values',return_value=saved):
            valuation = results.saved_valuation('hul')
        self.assertEqual(len(valuation['methods']),1)
        self.assertEqual(valuation['methods'][0]['base'],120)
        self.assertEqual(valuation['market_price_date'],'2026-10-16')
        self.assertIn('does not by itself establish',valuation['summary'])

    def test_preview_cannot_read_a_workbook_outside_outputs(self):
        path = self.root/'unrelated.xlsx'
        path.write_bytes(b'outside outputs')
        self.export(path)
        with patch.object(results,'read_saved_values',side_effect=AssertionError('must not read')):
            self.assertIsNone(results.saved_valuation('hul'))

    def test_older_dates_remain_dates_and_unknown_dates_are_not_today(self):
        self.assertEqual(results._date('2026-10-16T00:00:00.000Z'),'2026-10-16')
        self.assertEqual(results._date(1),'1899-12-31')
        self.assertIsNone(results._date('not a date'))
        self.assertIsNone(results._date(None))

    def test_empty_company_does_not_get_an_invented_valuation_or_buy_signal(self):
        report = results.company_results('hul')
        self.assertIsNone(report['valuation'])
        self.assertEqual(report['findings'],[])
        self.assertIn('not available',report['investor_summary'])

    def document_fixture(self):
        root = evidence_packs.pack_root('hul')
        root.mkdir(parents=True)
        pages = root / 'pages.json'
        pages.write_text(json.dumps([{'pack_page':1,'source_file':'HUL/results.pdf','original_page':3,
            'reasons':['statements'],'text':'Revenue from operations source fixture'}]))
        return {'pages':'pages.json', 'source_fingerprints':{'HUL/results.pdf':'fixture'},
                'artifact_hashes':{'pages.json':evidence_packs.digest_file(pages)},
                'source_files':1,'input_files':2,'selected_pages':1,'created_at':'2026-10-19T00:00:00+00:00',
                'warnings':['Unreadable document: HUL/scanned.pdf: OCR required.', 'No annual report identified.']}

    def test_company_documents_do_not_become_a_completed_valuation(self):
        manifest = self.document_fixture()
        with patch.object(evidence_packs,'read_manifest',return_value=manifest), patch.object(evidence_packs,'source_fingerprints',return_value=manifest['source_fingerprints']):
            report = results.company_results('hul')
        self.assertEqual(report['evidence']['pdf_url'],'/evidence/hul/pdf')
        self.assertEqual(report['evidence']['unreadable_files'],['HUL/scanned.pdf'])
        self.assertFalse(report['evidence']['financials_reviewed'])
        self.assertIsNone(report['valuation'])
        self.assertNotIn('artifact_hashes', report['evidence'])

    def test_document_downloads_retain_page_provenance_and_block_stale_files(self):
        from backend.excel_api import evidence_download
        from fastapi import HTTPException
        manifest = self.document_fixture()
        with patch.object(evidence_packs,'read_manifest',return_value=manifest), patch.object(evidence_packs,'source_fingerprints',return_value=manifest['source_fingerprints']):
            csv = evidence_download('hul','index')
            self.assertIn('HUL/results.pdf,3',csv.body.decode('utf-8'))
            self.assertIn('Original page 3',evidence_download('hul','text').body.decode('utf-8'))
        with patch.object(evidence_packs,'read_manifest',return_value=manifest), patch.object(evidence_packs,'source_fingerprints',return_value={}):
            self.assertIsNone(results.evidence_summary('hul')['pdf_url'])
            with self.assertRaises(HTTPException) as error:
                evidence_download('hul','text')
            self.assertEqual(error.exception.status_code,409)

    def test_document_download_cannot_serve_files_outside_company_pack(self):
        from backend.excel_api import evidence_download
        from fastapi import HTTPException
        manifest = self.document_fixture()
        manifest['pages'] = '../../unrelated.txt'
        (self.root/'unrelated.txt').write_text('Must not be served')
        with patch.object(evidence_packs,'read_manifest',return_value=manifest), patch.object(evidence_packs,'source_fingerprints',return_value=manifest['source_fingerprints']):
            with self.assertRaises(HTTPException) as error:
                evidence_download('hul','text')
        self.assertEqual(error.exception.status_code,404)

    def test_unprepared_valuation_is_rejected_before_building_or_model_calls(self):
        import asyncio
        from fastapi import HTTPException
        from backend.excel_api import export, CompanyRequest
        with self.assertRaises(HTTPException) as error:
            asyncio.run(export(CompanyRequest(company='hul')))
        self.assertEqual(error.exception.status_code,409)
        self.assertTrue(error.exception.detail['missing'])
        self.assertEqual(storage.rows('SELECT COUNT(*) AS n FROM excel_exports')[0]['n'],0)
        self.assertEqual(storage.rows('SELECT COUNT(*) AS n FROM research_runs')[0]['n'],0)

    def test_reported_figures_are_hidden_when_original_source_changes(self):
        source = self.sources/'hul/results.pdf'
        source.parent.mkdir()
        source.write_bytes(b'original fixture document')
        digest = evidence_packs.digest_file(source)
        with storage.database() as db:
            db.execute('INSERT INTO documents(id,company,title,original_url,retrieved_at,sha256,local_path) VALUES(?,?,?,?,?,?,?)',
                (1,'hul','Fixture','https://example.test/fixture',storage.now(),digest,'fixture.pdf'))
            db.execute('INSERT INTO passages(document_id,pdf_page,text) VALUES(?,?,?)',(1,2,'Revenue 300'))
            db.execute('INSERT INTO library_documents(company,relative_path,document_id) VALUES(?,?,?)',('hul','hul/results.pdf',1))
        brief = {'reported_results':{'source_file':'hul/results.pdf','source_sha256':digest,'source_page':2,
            'period':'Annual','scope':'Consolidated','qualification':'Source reported',
            'metrics':[{'label':'Revenue','display_value':'300','source_value':'300'}]}}
        self.assertEqual(results.reported_results('hul',brief)['metrics'][0]['display_value'],'300')
        source.write_bytes(b'changed source fixture')
        self.assertIsNone(results.reported_results('hul',brief))
