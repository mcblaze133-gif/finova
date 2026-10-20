"""Fresh-click contract: compact input, new checks and exact-run output."""
import asyncio
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch,AsyncMock
import httpx
from backend import storage,research,investigation,company_updates,model,results
from backend.main import app
from test_backend_audit import AuditFixture


class FreshTests(AuditFixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.sources=self.root/'sources'
        original=self.sources/'hul/original.pdf'
        original.parent.mkdir(parents=True)
        original.write_bytes(b'%PDF-original-test-reference')
        self.sha=hashlib.sha256(original.read_bytes()).hexdigest()
        (self.root/'config').mkdir()
        (self.root/'config/library.json').write_text(json.dumps({'source_folder':str(self.sources)}))
        with storage.database() as db:
            doc=db.execute("INSERT INTO documents(company,title,original_url,retrieved_at,sha256,local_path) VALUES('hul','Fixture','https://www.hul.co.in/fixture',?,?,?)",(storage.now(),self.sha,'data/raw/test.pdf')).lastrowid
            db.execute("INSERT INTO library_documents(company,relative_path,document_id) VALUES('hul','hul/original.pdf',?)",(doc,))
            self.ids=[]
            for n in (1,2,3):
                text=f'Revenue from operations fixture page {n}. Source date 2026-03-31. Consolidated INR crore.'
                self.ids.append(db.execute('INSERT INTO passages(document_id,pdf_page,text) VALUES(?,?,?)',(doc,n,text)).lastrowid)
        self.pack=self.root/'company-packs/hul'
        self.pack.mkdir(parents=True)
        from pypdf import PdfWriter
        writer=PdfWriter()
        for _ in range(2):writer.add_blank_page(width=600,height=800)
        with (self.pack/'compact.pdf').open('wb') as stream:writer.write(stream)
        pages=[{'source_file':'hul/original.pdf','source_sha256':self.sha,'original_page':n,'pack_page':n,'text':f'Revenue from operations fixture page {n}. Source date 2026-03-31. Consolidated INR crore.'} for n in (1,2)]
        (self.pack/'pages.json').write_text(json.dumps(pages))
        self.manifest={'signature':'test-signature','created_at':storage.now(),'pdf':'compact.pdf','pages':'pages.json','source_fingerprints':{'hul/original.pdf':self.sha},
                       'source_files':1,'input_files':1,'selected_pages':2,'reviewed_records':0,'warnings':[],
                       'artifact_hashes':{name:hashlib.sha256((self.pack/name).read_bytes()).hexdigest() for name in ('compact.pdf','pages.json')}}
        (self.pack/'manifest.json').write_text(json.dumps(self.manifest))

    async def test_compact_reader_uses_selected_pages_and_detects_tampering(self):
        rows,proof=investigation.prepared_passages('hul')
        self.assertEqual([r['id'] for r in rows],self.ids[:2])
        self.assertEqual(proof['selected_pages'],2)
        (self.pack/'pages.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'refreshed'):
            investigation.prepared_passages('hul')

    async def test_two_clicks_do_not_reuse_checks_models_or_previous_results(self):
        statement={'text':'This candidate is not substantiated by the available evidence.','citations':[{'passage_id':self.ids[0],'excerpt_id':0}]}
        plan=research.Plan(hypotheses=[{'question':'Does revenue growth reflect a changed reporting basis?','alternative':'Revenue reporting basis changed between periods','search_terms':'revenue operations'}])
        analysis=research.Analysis(sufficient=False,discovery=statement,significance=[statement]*3,timeline=[],counterargument=statement,
            falsification_condition='Comparable audited revenue disclosures would resolve the missing comparison.',limitations=[])
        review=research.Review(verdict='rejected',counterargument=statement,falsification_condition=analysis.falsification_condition,reasons=['Insufficient fixture evidence.'])
        async def news(run_id):
            result={'events':[],'news_leads':[],'limitations':['Fresh fixture coverage incomplete.']}
            with storage.database() as db:
                db.execute("UPDATE company_update_runs SET status='partial',result_json=?,updated_at=? WHERE id=?",(json.dumps(result),storage.now(),run_id))
                db.execute("UPDATE research_runs SET status='partial' WHERE id=?",(run_id,))
            return result
        model_outputs=[plan,research.Extracted(facts=[]),analysis,review]*2
        with patch.object(model,'model_settings',return_value=('test-only-secret','fixture')),patch('backend.evidence_packs.refresh',return_value=self.manifest),patch.object(company_updates,'execute',new=AsyncMock(side_effect=news)) as check,patch.object(investigation,'public_search',new=AsyncMock(return_value=[])),patch.object(research,'generate',new=AsyncMock(side_effect=model_outputs)) as generate,patch.object(research.documents,'discover',side_effect=AssertionError('Must not recrawl originals')),patch.object(results,'saved_valuation',side_effect=AssertionError('Must not load previous valuation')):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                jobs=[]
                for _ in range(2):
                    response=await client.post('/investigations',json={'company':'hul'})
                    self.assertEqual(response.status_code,202,response.text)
                    job=response.json();jobs.append(job)
                    from backend.api import TASKS
                    await asyncio.gather(*list(TASKS))
                    report=(await client.get(job['report_url'])).raise_for_status().json()
                    self.assertEqual(report['investigation']['run_id'],job['run_id'])
                    self.assertEqual(report['freshness']['run_id'],job['run_id'])
                    self.assertIsNone(report['valuation'])
                    self.assertFalse(report['findings'])
                    self.assertIsNone(report['reported_results'])
                self.assertNotEqual(jobs[0]['run_id'],jobs[1]['run_id'])
                # Even after a newer run finishes, the first URL returns only its own result.
                first=(await client.get(jobs[0]['report_url'])).raise_for_status().json()
                self.assertEqual(first['investigation']['run_id'],jobs[0]['run_id'])
        self.assertEqual(check.await_count,2)
        self.assertNotEqual(check.call_args_list[0].args[0],check.call_args_list[1].args[0])
        self.assertEqual(generate.await_count,8)
        extraction_calls=[c for c in generate.call_args_list if c.args[1]=='extractor']
        self.assertEqual(len(extraction_calls),2)
        for c in extraction_calls:self.assertNotIn(self.ids[2],[p['id'] for p in c.args[2]['passages']])

    async def test_quota_failure_starts_nothing_and_returns_no_previous_report(self):
        with patch.object(model,'model_settings',return_value=('test-only-secret','fixture')),patch.object(model,'require_capacity',side_effect=model.ModelUnavailable('Fresh run quota unavailable')):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.post('/investigations',json={'company':'hul'})
        self.assertEqual(response.status_code,429)
        self.assertEqual(storage.rows('SELECT * FROM research_runs'),[])

    async def test_missing_page_reference_does_not_fall_back_to_full_archive(self):
        with storage.database() as db:
            db.execute('DELETE FROM passages WHERE id=?',(self.ids[1],))
        with self.assertRaisesRegex(ValueError,'lost their original references'):
            investigation.prepared_passages('hul')

    async def test_running_fresh_report_does_not_fall_back(self):
        run_id=research.create_run(research.RunRequest(company='hul',force_fresh=True,evidence_pack_only=True))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.get(f'/investigations/{run_id}/report')
        self.assertEqual(response.status_code,409)

    async def test_provider_refusal_in_news_stops_further_research_calls(self):
        async def refused(run_id):
            payload={'events':[],'news_leads':[],'limitations':['Provider quota refusal.'],'provider_status':429}
            with storage.database() as db:
                db.execute("UPDATE company_update_runs SET status='partial',result_json=? WHERE id=?",(json.dumps(payload),run_id))
                db.execute("UPDATE research_runs SET status='partial' WHERE id=?",(run_id,))
            return payload
        with patch.object(model,'model_settings',return_value=('test-only-secret','fixture')),patch('backend.evidence_packs.refresh',return_value=self.manifest),patch.object(company_updates,'execute',new=AsyncMock(side_effect=refused)),patch.object(research,'generate',new=AsyncMock()) as generate:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                job=(await client.post('/investigations',json={'company':'hul'})).raise_for_status().json()
                from backend.api import TASKS
                await asyncio.gather(*list(TASKS))
                report=(await client.get('/runs/'+job['run_id']+'/report')).raise_for_status().json()
        generate.assert_not_awaited()
        self.assertEqual(report['external_updates']['provider_status'],429)
        self.assertEqual(report['status'],'partial')

    async def test_service_failure_in_news_stops_further_research_calls(self):
        async def refused(run_id):
            payload={'events':[],'news_leads':[],'limitations':['Provider service unavailable.'],'provider_status':503}
            with storage.database() as db:
                db.execute("UPDATE company_update_runs SET status='partial',result_json=? WHERE id=?",(json.dumps(payload),run_id))
                db.execute("UPDATE research_runs SET status='partial' WHERE id=?",(run_id,))
            return payload
        with patch.object(model,'model_settings',return_value=('test-only-secret','fixture')),patch('backend.evidence_packs.refresh',return_value=self.manifest),patch.object(company_updates,'execute',new=AsyncMock(side_effect=refused)),patch.object(research,'generate',new=AsyncMock()) as generate:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                job=(await client.post('/investigations',json={'company':'hul'})).raise_for_status().json()
                from backend.api import TASKS
                await asyncio.gather(*list(TASKS))
                report=(await client.get('/runs/'+job['run_id']+'/report')).raise_for_status().json()
        generate.assert_not_awaited()
        self.assertEqual(report['external_updates']['provider_status'],503)
        self.assertEqual(report['status'],'partial')
