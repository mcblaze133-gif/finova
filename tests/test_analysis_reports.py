"""Fresh report orchestration failures and isolation, with no real model calls."""
import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
import httpx
from backend import storage,analysis_reports as ar,model,research
from backend.main import app
from test_backend_audit import AuditFixture

class ReportTests(AuditFixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.manifest={'signature':'current','source_fingerprints':{'source.pdf':'hash'}}
        self.build_args=[]
        self.section_check=AsyncMock()
        self.enterContext(patch('backend.sector_research.complete',new=self.section_check))
        self.enterContext(patch.object(ar.excel_engine,'company_package',return_value={'historical_statements':{'periods':[]}}))
        self.targeted_check=AsyncMock(return_value={'signals':[],'retrieval_audit':[{'side':'competitive_evidence','originals':[]}]})
        self.enterContext(patch('backend.research_gaps.investigate',new=self.targeted_check))

    async def fresh_research(self,run_id):
        update_id='u'+run_id[1:]
        now=storage.now()
        raw={'status':'partial','created_at':now,'evidence_pack_read':{'signature':'current','physical_pdf_review':{'read_at':now,'pages':[1]}},'update_run_id':update_id}
        with storage.database() as db:
            db.execute("INSERT INTO research_runs(id,company,created_at,updated_at,evidence_cutoff,status,stage,request_json) VALUES(?,'hul',?,?,?,'partial','finished','{}')",(update_id,now,now,now[:10]))
            db.execute("INSERT INTO company_update_runs VALUES(?,'hul',?,?,'partial','finished','{}',NULL)",(update_id,now,now))
            db.execute("UPDATE research_runs SET status='partial',report_json=? WHERE id=?",(json.dumps(raw),run_id))

    async def fresh_excel(self,company,export_id,**kwargs):
        self.assertGreater(self.section_check.await_count,len(self.build_args))
        self.build_args.append((company,export_id,kwargs))
        self.assertTrue(kwargs['force_rebuild']);self.assertFalse(kwargs['refresh_research']);self.assertTrue(kwargs['research_update_id'])
        with storage.database() as db:
            db.execute("INSERT INTO excel_exports(id,company,created_at,status,input_json,workbook_path) VALUES(?,?,?,'exported','{}','fixture.xlsx')",(export_id,company,storage.now()))
        return {'status':'exported','cached':False}

    async def fresh_pdf(self,folder,payload):
        target=folder/'report.pdf';target.write_bytes(b'%PDF-fresh-report-fixture');return target

    async def test_two_clicks_build_new_research_new_excel_new_pdf(self):
        with patch.object(ar.excel_engine,'valuation_readiness',return_value={'can_build':True}),patch.object(model,'model_settings',return_value=('fixture','fixture')),patch.object(model,'require_capacity'),patch.object(ar.research,'execute',new=AsyncMock(side_effect=self.fresh_research)) as reads,patch.object(ar.excel_engine,'export_company',new=AsyncMock(side_effect=self.fresh_excel)),patch.object(ar.evidence_packs,'read_manifest',return_value=self.manifest),patch.object(ar.evidence_packs,'source_fingerprints',return_value=self.manifest['source_fingerprints']),patch.object(ar,'snapshot',side_effect=lambda *a:{'valuation':{'methods':[]},'report_id':a[3]}),patch.object(ar,'make_pdf',new=AsyncMock(side_effect=self.fresh_pdf)),patch.object(ar.results,'saved_valuation',side_effect=AssertionError('No previous valuation')):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                jobs=[]
                for _ in range(2):
                    response=await client.post('/analysis-reports',json={'company':'hul'});self.assertEqual(response.status_code,202,response.text)
                    job=response.json();jobs.append(job)
                    await asyncio.gather(*list(ar.TASKS))
                    state=(await client.get(job['status_url'])).json()
                    self.assertEqual(state['status'],'partial');self.assertTrue(state['pdf_url'])
                    pdf=await client.get(state['pdf_url']);self.assertEqual(pdf.status_code,200);self.assertEqual(pdf.headers['cache-control'],'no-store')
                self.assertNotEqual(jobs[0]['report_id'],jobs[1]['report_id'])
                first=(await client.get(jobs[0]['status_url'])).json();self.assertIn(jobs[0]['report_id'],first['pdf_url'])
        self.assertEqual(reads.await_count,2)
        self.assertEqual(self.section_check.await_count,2)
        self.assertEqual(self.targeted_check.await_count,2)
        for call in self.section_check.await_args_list:
            self.assertIn('targeted_research',call.args[0])
            self.assertEqual(call.args[0]['targeted_research']['retrieval_audit'][0]['side'],'competitive_evidence')
        self.assertTrue(all(args[2].get('analysis_report_id') for args in self.build_args))
        self.assertNotEqual(self.build_args[0][1],self.build_args[1][1])
        self.assertNotEqual(self.build_args[0][2]['research_update_id'],self.build_args[1][2]['research_update_id'])
        for r in storage.rows("SELECT request_json FROM research_runs WHERE request_json!='{}'"):
            q=json.loads(r['request_json']);self.assertTrue(q['force_fresh'] and q['refresh'] and q['evidence_pack_only'])

    async def test_quota_refusal_creates_no_report_and_no_research(self):
        with patch.object(ar.excel_engine,'valuation_readiness',return_value={'can_build':True}),patch.object(model,'model_settings'),patch.object(model,'require_capacity',side_effect=model.ModelUnavailable('Fresh capacity unavailable')):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
                r=await c.post('/analysis-reports',json={'company':'hul'})
        self.assertEqual(r.status_code,429)
        self.assertFalse(storage.rows('SELECT * FROM analysis_reports'));self.assertFalse(storage.rows('SELECT * FROM research_runs'))

    async def test_real_home_page_is_utf8_and_contains_reader_controls(self):
        original=Path(ar.__file__).resolve().parent.parent
        with patch.object(storage,'PROJECT_DIR',original):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
                response=await c.get('/')
        self.assertEqual(response.status_code,200)
        text=response.content.decode('utf-8')
        self.assertIn('Read research report',text)
        self.assertIn('Edits to a downloaded workbook stay in that copy.',text)

    async def test_report_view_and_summary_match_the_download(self):
        rid='c'*32;folder=self.root/'outputs'/rid;folder.mkdir(parents=True)
        path=folder/'research.pdf';path.write_bytes(b'%PDF-fixture')
        payload={'research_excel_linked':True,'valuation':{'weighted':{'bear':80,'base':100,'bull':120}},
                 'coverage':{'areas':[{'area':'Business and products','status':'complete'},{'area':'Financial statements','status':'partial'}]},
                 'news':{'checked_at':'2026-10-20T00:00:00Z'}}
        with storage.database() as db:db.execute("INSERT INTO analysis_reports(id,company,created_at,updated_at,status,stage,pdf_path,snapshot_json) VALUES(?,'hul',?,?,'partial','finished',?,?)",(rid,storage.now(),storage.now(),str(path),json.dumps(payload)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            state=(await c.get('/analysis-reports/'+rid)).json()
            self.assertTrue(state['research_excel_linked'])
            self.assertEqual(state['overview']['research_areas'],1)
            self.assertEqual(state['overview']['valuation']['base'],100)
            view=await c.get(state['pdf_url']+'?view=true');download=await c.get(state['pdf_url'])
            self.assertEqual(view.content,download.content)
            self.assertTrue(view.headers['content-disposition'].startswith('inline'))
            self.assertTrue(download.headers['content-disposition'].startswith('attachment'))

    async def test_running_report_cannot_download_previous_pdf(self):
        rid='a'*32
        with storage.database() as db:db.execute("INSERT INTO analysis_reports(id,company,created_at,updated_at,status,stage) VALUES(?,'hul',?,?,'running','research')",(rid,storage.now(),storage.now()))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            r=await c.get(f'/analysis-reports/{rid}/pdf');self.assertEqual(r.status_code,409)
            r=await c.get('/analysis-reports/not-valid/pdf');self.assertEqual(r.status_code,404)

    async def test_validation_outputs_are_explicitly_identified(self):
        rid='b'*32
        with storage.database() as db:
            db.execute("INSERT INTO analysis_reports(id,company,created_at,updated_at,status,stage,snapshot_json) VALUES(?,'hul',?,?,'partial','finished',?)",(rid,storage.now(),storage.now(),json.dumps({'validation_only':True})))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            response=await c.get('/analysis-reports/'+rid)
        self.assertTrue(response.json()['validation_only'])

    async def test_missing_physical_pdf_review_stops_before_valuation(self):
        rid='a'*32;research_id=research.create_run(research.RunRequest(company='hul',force_fresh=True))
        with storage.database() as db:
            db.execute("UPDATE research_runs SET status='partial',report_json='{}' WHERE id=?",(research_id,))
            db.execute("INSERT INTO analysis_reports(id,company,created_at,updated_at,status,stage,research_run_id) VALUES(?,'hul',?,?,'queued','queued',?)",(rid,storage.now(),storage.now(),research_id))
        with patch.object(ar.research,'execute',new=AsyncMock()),patch.object(ar.excel_engine,'export_company',new=AsyncMock()) as build:
            await ar.execute(rid)
        build.assert_not_awaited();self.assertEqual(ar.row(rid)['status'],'failed');self.assertIsNone(ar.row(rid)['pdf_path'])

    def test_sector_claims_require_given_source_excerpts(self):
        s={'text':'A company-specific claim','citations':[{'passage_id':1,'quote':'Fabricated original quote'}]}
        a=research.Analysis(sufficient=False,discovery=s,significance=[s]*3,timeline=[],counterargument=s,
            falsification_condition='Verified contrary financial evidence would invalidate this claim.',limitations=[],
            sector_sections=[{'topic':'Capital allocation','statements':[s],'investor_use':'Compare investment returns with the available cash evidence.'}])
        with self.assertRaisesRegex(ValueError,'does not match'):research.check_statements(a,[{'id':1,'text':'A different original statement'}])
