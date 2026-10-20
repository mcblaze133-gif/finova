import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from backend import storage, library, evidence_packs as packs, excel_engine


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        with patch.object(storage, 'DB_PATH', self.root / 'test.sqlite'):
            with storage.database() as db:
                db.executescript(storage.SCHEMA)
                for path in (storage.PROJECT_DIR / 'schemas').glob('*.sql'):
                    db.executescript(path.read_text())
        self.patches = [patch.object(storage, 'PROJECT_DIR', self.root),
                        patch.object(storage, 'DATA_DIR', self.root / 'data'),
                        patch.object(storage, 'DB_PATH', self.root / 'test.sqlite'),
                        patch.object(library, 'root_folder', return_value=self.root / 'sources')]
        for p in self.patches:
            p.start()
        self.source = self.root / 'sources' / 'demo' / 'Analyst_Deck_Q1_27.pdf'
        self.source.parent.mkdir(parents=True)
        self.pdf(self.source, 3)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def pdf(self, path, count, label='Fixture source page'):
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        for number in range(count):
            page = writer.add_blank_page(width=200, height=300)
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
                NameObject('/F1'): DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                    NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})})})
            content = DecodedStreamObject()
            content.set_data(f'BT /F1 12 Tf 10 100 Td ({label} {number} with enough searchable financial narrative text) Tj ET'.encode())
            page[NameObject('/Contents')] = writer._add_object(content)
        writer.write(path)

    def seed(self):
        result = library.import_pdf('demo', 'demo/' + self.source.name)
        with storage.database() as db:
            db.execute('DELETE FROM passages WHERE document_id=?', (result['document_id'],))
            db.executemany('INSERT INTO passages(document_id,pdf_page,text) VALUES(?,?,?)', [
                (result['document_id'], 1, 'Q1 FY27 results'),
                (result['document_id'], 2, 'Volume growth and commodity prices'),
                (result['document_id'], 3, 'Related party contingent liability specialword')])
        return result['document_id']

    def render(self, args, **kwargs):
        prefix = Path(args[-1])
        from pypdf import PdfReader
        for number in range(1, len(PdfReader(args[-2]).pages)+1):
            prefix.with_name(prefix.name + f'-{number}.png').write_bytes(b'fixture screenshot')
        return type('Result', (), {'returncode': 0})()

    def test_unchanged_pack_avoids_parsing_and_rendering_and_detects_tampering(self):
        self.seed()
        with patch.object(packs.shutil, 'which', return_value='fixture-renderer'), patch.object(packs.subprocess, 'run', side_effect=self.render):
            first = packs.refresh('demo')
            self.assertEqual(first['selected_pages'], 3)
            with patch.object(packs.subprocess, 'run', side_effect=AssertionError('must reuse')), patch('pypdf.PdfReader', side_effect=AssertionError('must reuse')):
                again = packs.refresh('demo')
            self.assertTrue(again['reused'])
            self.assertEqual(again['page_renders'], 0)
            (packs.pack_root('demo') / first['pdf']).write_bytes(b'tampered')
            self.assertFalse(packs.refresh('demo')['reused'])

    def test_changed_same_filename_replaces_mapping_and_keeps_archive(self):
        old = self.seed()
        self.pdf(self.source, 4)
        new = library.import_pdf('demo', 'demo/' + self.source.name)['document_id']
        self.assertNotEqual(old, new)
        self.assertEqual([r['document_id'] for r in storage.rows('SELECT document_id FROM library_documents')], [new])
        self.assertEqual(len(storage.rows('SELECT id FROM documents')), 2)

    def test_search_falls_back_and_rejects_stale_source(self):
        self.seed()
        result = packs.search('demo', 'specialword')
        self.assertEqual(result['scope'], 'full original fallback')
        self.assertEqual(len(result['results']), 1)
        self.source.unlink()
        self.assertEqual(packs.search('demo', 'specialword')['results'], [])

    def test_history_selection_preserves_reviewed_page_context_and_excludes_standalone(self):
        pages = {1:'Standalone balance sheet inventories', 2:'Standalone notes',
                 3:'Consolidated Balance Sheet Non-current assets', 4:'continued financial table',
                 5:'note unrelated phrase', 6:'evidence supporting reviewed figure', 7:'table continuation'}
        selected = packs.select_pages(pages, mandatory=[6], annual=True, detailed=False)
        self.assertNotIn(1, selected)
        self.assertTrue({3,4,5,6,7}.issubset(selected))

    def test_company_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            packs.refresh('../elsewhere')
        with self.assertRaises(ValueError):
            library.import_pdf('demo', '../../outside.pdf')

    def test_older_transcripts_and_presentations_are_not_dropped(self):
        self.seed()
        for year in (2022,2023,2024,2025):
            for kind in ('Transcript','Presentation'):
                self.pdf(self.source.with_name(f'{kind}_{year}.pdf'),3,label=f'{kind} {year} volume growth and margin guidance')
        with patch.object(packs.shutil,'which',return_value='fixture-renderer'),patch.object(packs.subprocess,'run',side_effect=self.render):
            manifest=packs.refresh('demo')
        self.assertEqual(len(manifest['source_index']),9)
        self.assertTrue(all(d['selected_original_pages'] for d in manifest['source_index']))
        self.assertEqual({d['period_sort_hint_unverified'][0] for d in manifest['source_index']},{22,23,24,25,27})

    def test_old_annual_notes_and_front_operating_context_are_retained(self):
        pages={1:'Annual Report 2022',2:'Our outlook for volume growth and margin recovery',
               3:'Other information',4:'Consolidated Balance Sheet Non-current assets',
               5:'continued statement',6:'ordinary text',7:'ordinary text',8:'Lease liabilities and capital commitments',9:'note continuation'}
        selected=packs.select_pages(pages,annual=True,detailed=True)
        self.assertTrue({2,4,5,8,9}.issubset(selected))

    def test_expanding_same_source_reuses_verified_page_images(self):
        self.pdf(self.source,6)
        doc=library.import_pdf('demo','demo/'+self.source.name)['document_id']
        with storage.database() as db:
            db.execute('DELETE FROM passages WHERE document_id=?',(doc,))
            db.executemany('INSERT INTO passages(document_id,pdf_page,text) VALUES(?,?,?)',
                           [(doc,n,'Volume growth' if n==1 else 'ordinary text') for n in range(1,7)])
        with patch.object(packs.shutil,'which',return_value='fixture-renderer'),patch.object(packs.subprocess,'run',side_effect=self.render):
            first=packs.refresh('demo')
            self.assertEqual(first['page_renders'],2)
            with storage.database() as db:db.execute("UPDATE passages SET text='Margin recovery guidance' WHERE document_id=? AND pdf_page=6",(doc,))
            updated=packs.refresh('demo')
        self.assertEqual(updated['selected_pages'],4)
        self.assertEqual(updated['page_renders'],2)

    def test_folder_aliases_and_generated_pack_exclusion(self):
        config = self.root / 'config'
        config.mkdir()
        (config / 'company_folders.json').write_text(json.dumps({'nestle-india': 'demo'}))
        generated = self.source.parent / 'SignalAI Evidence' / 'versions' / 'hash'
        generated.mkdir(parents=True)
        self.pdf(generated / 'Valuation evidence.pdf', 2)
        (generated / 'Source index.csv').write_text('generated data')
        self.assertEqual(list(packs.source_fingerprints('nestle-india')), ['demo/' + self.source.name])
        self.assertEqual(len(library.inventory()['files']), 1)
        (config / 'company_folders.json').write_text(json.dumps({'nestle-india': '../escape'}))
        with self.assertRaises(ValueError):
            library.company_folder('nestle-india')

    def test_financial_releases_not_dropped_by_recent_deck_filter(self):
        self.seed()
        new = self.source.with_name('quarterly_results.pdf')
        self.source.rename(new)
        self.source = new
        with patch.object(packs.shutil, 'which', return_value='fixture-renderer'), patch.object(packs.subprocess, 'run', side_effect=self.render):
            manifest = packs.refresh('demo')
        self.assertEqual(manifest['selected_pages'], 3)
        self.assertEqual(manifest['source_index'][0]['kind'], 'financial update')
        self.assertTrue(any('No annual report' in warning for warning in manifest['warnings']))

    def test_published_pack_preserves_sources_and_cannot_reingest_itself(self):
        from tools.prepare_all_company_evidence import prepare, publish
        from pypdf import PdfReader
        self.pdf(self.source, 3, label='Volume growth and commodity prices')
        before = packs.digest_file(self.source)
        with patch.object(packs.shutil, 'which', return_value='fixture-renderer'), patch.object(packs.subprocess, 'run', side_effect=self.render):
            result = prepare('demo')
            publish(result)
            self.assertTrue(packs.refresh('demo')['reused'])
        self.assertEqual(packs.digest_file(self.source), before)
        self.assertEqual(len(library.inventory()['files']), 1)
        self.assertEqual(len(PdfReader(result['published_pdf']).pages), 3)
        self.assertIn('Volume growth', (Path(result['published_pdf']).parent / 'Searchable evidence.txt').read_text())
        self.assertTrue(Path(result['published_index']).is_file())

    def test_publish_rejects_changed_original(self):
        from tools.prepare_all_company_evidence import prepare, publish
        self.pdf(self.source, 3, label='Volume growth and commodity prices')
        with patch.object(packs.shutil, 'which', return_value='fixture-renderer'), patch.object(packs.subprocess, 'run', side_effect=self.render):
            result = prepare('demo')
        self.pdf(self.source, 4)
        with self.assertRaisesRegex(ValueError, 'Original files changed'):
            publish(result)

    def test_complex_local_pdf_fallback_preserves_original_page_numbers(self):
        from backend import documents
        from pypdf.errors import LimitReachedError
        expected, _ = documents.extract(self.source.read_bytes(), 'application/pdf')
        original_save = documents.save_document
        calls = []
        def save(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise LimitReachedError('Reached maximum number of tokens per stream.')
            return original_save(*args, **kwargs)
        with patch.object(documents, 'save_document', side_effect=save), patch.object(library, 'extract_local_pdf_fallback', return_value=expected):
            result = library.import_pdf('demo', 'demo/' + self.source.name)
        stored = storage.rows('SELECT pdf_page,text FROM passages WHERE document_id=? ORDER BY pdf_page', (result['document_id'],))
        self.assertEqual([r['pdf_page'] for r in stored], [1,2,3])
        self.assertEqual([r['text'] for r in stored], expected)

    def test_local_fallback_does_not_override_page_limit(self):
        from backend import documents
        with patch.object(documents, 'save_document', side_effect=ValueError('PDF exceeds page limit.')), patch.object(library, 'extract_local_pdf_fallback') as fallback:
            with self.assertRaisesRegex(ValueError, 'page limit'):
                library.import_pdf('demo', 'demo/' + self.source.name)
        fallback.assert_not_called()

    def test_local_plain_fallback_keeps_pages_when_poppler_absent(self):
        import shutil
        from backend import documents
        from pypdf import PdfReader
        with patch.object(shutil, 'which', return_value=None), patch.object(Path, 'is_file', return_value=False):
            pages = library.extract_local_pdf_fallback(self.source)
        expected = [p.extract_text() or '' for p in PdfReader(self.source).pages]
        self.assertEqual(pages, expected)
        self.assertEqual(len(pages), 3)
        with patch.object(shutil, 'which', return_value=None), patch.object(Path, 'is_file', return_value=False), patch.object(documents, 'MAX_TEXT', 10):
            with self.assertRaisesRegex(ValueError, 'text limits'):
                library.extract_local_pdf_fallback(self.source)

    def test_layout_padding_limit_can_use_bounded_local_fallback(self):
        from backend import documents
        expected, _ = documents.extract(self.source.read_bytes(), 'application/pdf')
        original_save = documents.save_document
        calls = []
        def save(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ValueError('PDF exceeds extracted text limit.')
            return original_save(*args, **kwargs)
        with patch.object(documents, 'save_document', side_effect=save), patch.object(library, 'extract_local_pdf_fallback', return_value=expected):
            result = library.import_pdf('demo', 'demo/' + self.source.name)
        self.assertEqual(len(storage.rows('SELECT id FROM passages WHERE document_id=?', (result['document_id'],))), 3)

    def test_failed_poppler_falls_back_to_plain_text_not_none(self):
        import shutil
        import subprocess
        from types import SimpleNamespace
        with patch.object(shutil, 'which', return_value='fixture-pdftotext'), patch.object(subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            pages = library.extract_local_pdf_fallback(self.source)
        self.assertIsInstance(pages, list)
        self.assertEqual(len(pages), 3)
        self.assertTrue(all('financial' in page.lower() for page in pages))

    def test_recursive_navigation_fallback_preserves_printed_page_streams(self):
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        self.seed()
        original_add = PdfWriter.add_page
        def add(writer, page, excluded_keys=()):
            if '/Annots' not in excluded_keys:
                raise PdfReadError("RecursionError('maximum recursion depth exceeded')")
            return original_add(writer, page, excluded_keys=excluded_keys)
        with patch.object(packs.shutil, 'which', return_value='fixture-renderer'), patch.object(packs.subprocess, 'run', side_effect=self.render), patch.object(PdfWriter, 'add_page', new=add):
            result = packs.refresh('demo')
        combined = PdfReader(packs.pack_root('demo') / result['pdf'])
        original = PdfReader(self.source)
        self.assertEqual(combined.pages[1].get_contents().get_data(), original.pages[1].get_contents().get_data())
        self.assertTrue(any('Interactive annotations omitted' in warning for warning in result['warnings']))

    def test_period_sort_uses_cover_for_opaque_filename(self):
        self.assertGreater(packs.period_hint('Transcript_1458e73769.pdf', {1:"Q4 FY '26 Earnings"}),
                           packs.period_hint('Transcript_Analyst_Call_Q3_25_26.pdf', {1:'Q3 FY 25-26 Earnings'}))
        self.assertGreater(packs.period_hint('Q4FY26 Investor Presentation.pdf', {1:'Investor presentation'}),
                           packs.period_hint('012726_Q3FY26_Investor_Presentation.pdf', {1:'Investor presentation'}))

    def test_changed_source_excludes_previously_reviewed_financial_input(self):
        from backend.valuation_spec import FinancialRecord
        record = FinancialRecord.model_validate({'company':'demo','metric':'revenue','value':'100',
            'unit':'INR','currency':'INR','period_start':'2025-04-01','period_end':'2026-03-31',
            'accounting_scope':'consolidated','operations_scope':'total','segment':'group',
            'definition':'Revenue from operations','source_type':'historical','source_url':self.source.as_uri(),
            'source_file':'demo/'+self.source.name,'source_page':'2','source_date':'2026-04-20',
            'review_status':'source_verified','source_sha256':packs.digest_file(self.source),
            'source_quote':'Reviewed financial source fixture','review_note':'Fixture review only'})
        with storage.database() as db:
            db.execute('INSERT INTO library_records VALUES(?,?,?,?,?)', ('fixture','demo',record.model_dump_json(),'fixture',storage.now()))
        self.assertEqual(excel_engine.company_package('demo')['financials']['revenue'][-1],100)
        self.pdf(self.source, 4)
        updated = excel_engine.company_package('demo')
        self.assertIsNone(updated['financials']['revenue'][-1])
        self.assertTrue(any('excluded' in issue for issue in updated['issues']))

    def test_excel_reuse_preserves_edited_workbook_and_input_changes_invalidate(self):
        package = {'company_id':'demo', 'created_at':'a', 'assumptions':[1], 'issues':[]}
        fingerprint = excel_engine.input_fingerprint(package)
        path = self.root / 'outputs' / 'first' / 'book.xlsx'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'original workbook fixture')
        with storage.database() as db:
            db.execute('INSERT INTO excel_exports VALUES(?,?,?,?,?,?,?)', ('first','demo','today','exported','{}',str(path),None))
            db.execute('INSERT INTO excel_export_cache VALUES(?,?,?)', (fingerprint,'first',packs.digest_file(path)))
        self.assertEqual(excel_engine.cached_export(fingerprint)['id'], 'first')
        self.assertEqual(excel_engine.input_fingerprint(dict(package, created_at='b')), fingerprint)
        self.assertIsNone(excel_engine.cached_export(excel_engine.input_fingerprint(dict(package, assumptions=[2]))))
        from backend import company_updates
        from unittest.mock import AsyncMock
        with patch.object(excel_engine, 'company_package', return_value=package), patch.object(packs, 'source_fingerprints', return_value={}), patch.object(company_updates,'for_valuation',new=AsyncMock(return_value={'status':'partial'})) as check:
            result = asyncio.run(excel_engine.export_company('demo'))
        check.assert_awaited_once_with('demo')
        self.assertTrue(result['cached'])
        path.write_bytes(b'analyst edited workbook')
        self.assertIsNone(excel_engine.cached_export(fingerprint))
        self.assertEqual(path.read_bytes(), b'analyst edited workbook')
