"""Failure-path regressions. Isolated database; no real network or AI calls."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from backend import storage, model, research, company_updates, excel_api, excel_engine
from backend.backup import backup, verify_restore


class AuditFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        project = storage.PROJECT_DIR
        self.patches = [patch.object(storage,'DB_PATH',self.root/'signalai.sqlite')]
        self.patches[0].start()
        with storage.database() as db:
            db.executescript(storage.SCHEMA)
            for path in sorted((project/'schemas').glob('*.sql')):
                db.executescript(path.read_text())
        self.patches.append(patch.object(storage,'PROJECT_DIR',self.root))
        self.patches[-1].start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def run_row(self, id, created, calls=0):
        with storage.database() as db:
            db.execute('INSERT INTO research_runs(id,company,created_at,updated_at,evidence_cutoff,status,stage,request_json,model_calls) VALUES(?,?,?,?,?,?,?,?,?)',
                       (id,'hul',created,created,created[:10],'partial','finished','{}',calls))


class PersistenceAudit(AuditFixture, unittest.TestCase):
    def test_normal_daily_limit_is_200_preserves_usage_and_enforces_boundary(self):
        self.assertEqual(model.DAILY_REQUEST_LIMIT,200)
        timestamp=storage.now()
        self.run_row('used',timestamp,199)
        self.run_row('next',timestamp)
        model.require_capacity(1)
        with self.assertRaises(model.ModelUnavailable):model.require_capacity(2)
        model.reserve_call('next')
        with storage.database() as db:
            self.assertEqual(model._daily_limit(db,timestamp[:10]),200)
            self.assertEqual(model._daily_calls(db,timestamp[:10]),200)
        with self.assertRaises(model.ModelUnavailable):model.reserve_call('next')

    def test_twenty_more_preserves_usage_is_idempotent_and_expires(self):
        self.enterContext(patch.object(model, 'DAILY_REQUEST_LIMIT', 25))
        from datetime import date
        self.run_row('already-used','2026-10-19T10:00:00+00:00',35)
        with patch.object(storage,'now',return_value='2026-10-19T12:00:00+00:00'),patch.object(storage,'today_ist',return_value=date(2026,10,19)):
            model.approve_recording_allowance('Earlier user approval of ten extra recording attempts.')
            for _ in range(2):model.approve_recording_topup('explicit-twenty',20,'User explicitly said okay do 20 more recording attempts.')
            with storage.database() as db:
                self.assertEqual(model._daily_limit(db,'2026-10-19'),55)
                self.assertEqual(model._daily_calls(db,'2026-10-19'),35)
            model.require_capacity(20)
            with self.assertRaises(model.ModelUnavailable):model.require_capacity(21)
        with patch.object(storage,'now',return_value='2026-10-19T18:30:00+00:00'):
            with storage.database() as db:self.assertEqual(model._daily_limit(db,'2026-10-19'),25)

    def test_recording_allowance_is_ten_total_idempotent_and_expires_local_midnight(self):
        self.enterContext(patch.object(model, 'DAILY_REQUEST_LIMIT', 25))
        from datetime import date
        self.run_row('legacy','2026-10-19T10:00:00+00:00',25)
        self.run_row('recording-a','2026-10-19T10:00:00+00:00')
        self.run_row('recording-b','2026-10-19T10:00:00+00:00')
        with patch.object(storage,'now',return_value='2026-10-19T12:00:00+00:00'),patch.object(storage,'today_ist',return_value=date(2026,10,19)):
            grant=model.approve_recording_allowance('User explicitly approved ten attempts for today’s recording.')
            self.assertEqual(grant['expires_at'],'2026-10-19T18:30:00+00:00')
            model.require_capacity(5)
            for _ in range(8):model.reserve_call('recording-a')
            model.approve_recording_allowance('Repeated invocation must not stack another ten attempts.')
            for _ in range(2):model.reserve_call('recording-b')
            with self.assertRaises(model.ModelUnavailable):model.reserve_call('recording-b')
            with storage.database() as db:
                self.assertEqual(model._daily_calls(db,'2026-10-19'),35)
        with patch.object(storage,'now',return_value='2026-10-19T18:31:00+00:00'):
            with storage.database() as db:self.assertEqual(model._daily_limit(db,'2026-10-19'),25)
            with self.assertRaises(model.ModelUnavailable):model.reserve_call('recording-b')
        with patch.object(storage,'now',return_value='2026-10-20T00:01:00+00:00'):
            model.require_capacity(5)

    def test_readiness_blocks_missing_forecast_and_invalid_weights(self):
        from backend.valuation_spec import DRIVERS
        package = {'periods':['2026-03-31'], 'financials':{k:[100] for k in ('revenue','ebitda','da','operating_nwc','shares')},
                   'assumptions':[{'driver':d,'scenario':s,'values':['0']*5,'source_date':'2026-10-18'} for d in DRIVERS for s in ('bear','base','bull')],
                   'methods':[{'method':'DCF FCFF','applicable':'Yes','weight':1,'weight_rationale':'Fixture only'}],
                   'revenue_route':'Volume and price/mix','margin_route':'EBITDA margin',
                   'market':{'current_shares':100,'debt':0,'cash':0}}
        self.assertTrue(excel_engine.valuation_readiness('hul',package)['can_build'])
        next(a for a in package['assumptions'] if a['driver']=='ebitda_margin' and a['scenario']=='base')['values'][2]=None
        result = excel_engine.valuation_readiness('hul',package)
        self.assertFalse(result['can_build'])
        self.assertIn('base ebitda_margin',' '.join(result['missing']))
        package['methods'][0]['weight']=.5
        self.assertIn('100%',' '.join(excel_engine.valuation_readiness('hul',package)['missing']))

    def test_evidence_download_rejects_changed_pdf(self):
        from backend import evidence_packs
        root = self.root/'company-packs/hul'
        root.mkdir(parents=True)
        (root/'pack.pdf').write_bytes(b'tampered')
        manifest = {'pdf':'pack.pdf','source_fingerprints':{},'artifact_hashes':{'pack.pdf':'expected-hash'}}
        with patch.object(evidence_packs,'read_manifest',return_value=manifest),patch.object(evidence_packs,'source_fingerprints',return_value={}):
            with self.assertRaises(HTTPException) as caught:
                excel_api.evidence_pdf('hul')
        self.assertEqual(caught.exception.status_code,409)

    def test_midnight_calls_are_charged_to_actual_request_day(self):
        self.run_row('older-run','2026-10-18T23:59:00+00:00')
        with patch.object(storage,'now',return_value='2026-10-18T23:59:30+00:00'):
            model.reserve_call('older-run')
        self.run_row('legacy-today','2026-10-19T00:00:01+00:00',model.DAILY_REQUEST_LIMIT-1)
        with patch.object(storage,'now',return_value='2026-10-19T00:01:00+00:00'):
            model.reserve_call('older-run')
            with self.assertRaises(model.ModelUnavailable):
                model.reserve_call('older-run')
            with self.assertRaises(model.ModelUnavailable):
                model.reserve_probe()
        ledger = storage.rows('SELECT utc_day,calls FROM model_call_ledger WHERE run_id=? ORDER BY utc_day',('older-run',))
        self.assertEqual([r['calls'] for r in ledger],[1,1])
        self.assertEqual(storage.rows('SELECT model_calls FROM research_runs WHERE id=?',('older-run',))[0]['model_calls'],2)

    def test_simultaneous_news_refreshes_share_one_run(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(company_updates.create,['hul']*6))
        self.assertEqual(len({r[0] for r in results}),1)
        self.assertEqual(sum(r[1] for r in results),1)
        self.assertEqual(len(storage.rows('SELECT * FROM research_runs')),1)

    def test_backup_restores_models_configuration_and_evidence(self):
        workbook = self.root/'outputs'/'fixture'/'saved.bin'
        workbook.parent.mkdir(parents=True)
        workbook.write_bytes(b'saved-workbook-fixture')
        for relative in ('config/company_cases/hul.json','company-packs/hul/manifest.json'):
            p = self.root/relative
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('{}')
        (self.root/'.env').write_text('GEMINI_API_KEY=test-only-secret')
        dependencies = self.root/'excel/node_modules/example'
        dependencies.mkdir(parents=True)
        (dependencies/'dependency.bin').write_bytes(b'excluded dependency')
        with storage.database() as db:
            db.execute('INSERT INTO excel_exports(id,company,created_at,status,input_json,workbook_path) VALUES(?,?,?,?,?,?)',
                       ('saved','hul',storage.now(),'exported','{}',str(workbook)))
        backup(self.root/'backup')
        result = verify_restore(self.root/'backup',self.root/'restored')
        self.assertEqual(result['saved_workbooks_restored'],1)
        self.assertFalse((self.root/'restored/.env').exists())
        self.assertFalse((self.root/'restored/excel/node_modules').exists())
        db = sqlite3.connect(self.root/'restored/signalai.sqlite')
        path = db.execute('SELECT workbook_path FROM excel_exports').fetchone()[0]
        db.close()
        self.assertTrue(Path(path).is_relative_to(self.root/'restored'))
        self.assertEqual(Path(path).read_bytes(),workbook.read_bytes())
        self.assertTrue((self.root/'restored/config/company_cases/hul.json').is_file())
        self.assertTrue((self.root/'restored/company-packs/hul/manifest.json').is_file())

    def test_restore_rejects_changed_database(self):
        backup(self.root/'backup')
        with (self.root/'backup/signalai.sqlite').open('ab') as stream:
            stream.write(b'tampered')
        with self.assertRaisesRegex(ValueError,'database hash'):
            verify_restore(self.root/'backup',self.root/'restored')


class AsyncAudit(AuditFixture, unittest.IsolatedAsyncioTestCase):
    async def test_redirect_cannot_fetch_a_disallowed_source_path(self):
        from urllib.robotparser import RobotFileParser
        from backend import documents
        parser = RobotFileParser()
        parser.parse(['User-agent: *','Disallow: /private'])
        response = AsyncMock()
        response.status_code=302
        response.headers={'location':'/private/report.pdf'}
        stream = AsyncMock()
        stream.__aenter__.return_value=response
        remote = AsyncMock()
        remote.__aenter__.return_value=remote
        from unittest.mock import Mock
        remote.stream=Mock(return_value=stream)
        fetcher = documents.Fetcher(['example.com'])
        with patch.object(documents,'public_host',new=AsyncMock()),patch.object(documents.httpx,'AsyncClient',return_value=remote):
            with self.assertRaisesRegex(ValueError,'robots.txt'):
                await fetcher.raw('https://example.com/public',access_policy=parser)
        self.assertEqual(fetcher.requests,1)
        remote.stream.assert_called_once()

    async def test_waiting_valuation_tracks_its_refresh_not_a_newer_run(self):
        first,_ = company_updates.create('hul')
        with storage.database() as db:
            db.execute("UPDATE company_update_runs SET status='partial',result_json='{}' WHERE id=?",(first,))
            db.execute("UPDATE research_runs SET status='partial' WHERE id=?",(first,))
        second,_ = company_updates.create('hul')
        self.assertNotEqual(first,second)
        with patch.object(company_updates,'create',return_value=(first,False)),patch.object(company_updates.asyncio,'sleep',new=AsyncMock(side_effect=AssertionError('Completed matching run must not wait'))):
            result = await company_updates.for_valuation('hul')
        self.assertEqual(result['id'],first)

    async def test_simultaneous_exports_and_cancel_before_authoring(self):
        def readiness(company):
            time.sleep(.03)
            return {'can_build':True,'missing':[]}
        started = asyncio.Event()
        async def build(*args):
            started.set()
            await asyncio.Event().wait()
        with patch.object(excel_api,'EXPORT_ADMISSION',asyncio.Lock()), patch.object(excel_api.excel_engine,'valuation_readiness',side_effect=readiness), patch.object(excel_api.excel_engine,'export_company',side_effect=build):
            results = await asyncio.gather(*[excel_api.export(excel_api.CompanyRequest(company='hul')) for _ in range(2)],return_exceptions=True)
            self.assertEqual(sum(isinstance(r,dict) for r in results),1)
            errors = [r for r in results if isinstance(r,HTTPException)]
            self.assertEqual([r.status_code for r in errors],[409])
            await started.wait()
            tasks = list(excel_api.EXPORT_JOBS)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        self.assertEqual(storage.rows('SELECT status FROM excel_exports')[0]['status'],'interrupted')
        self.assertFalse(excel_api.EXPORT_JOBS)

    async def test_malformed_model_failure_is_sanitized_not_another_exception(self):
        self.run_row('malformed','2026-10-19T00:00:00+00:00')
        for body in ({'candidates':[None]},{'candidates':{}},{'candidates':'bad'}, {'candidates':[{'content':{'parts':[None]}}]}):
            client = AsyncMock()
            client.__aenter__.return_value = client
            client.post.return_value = httpx.Response(200,json=body)
            with patch.object(model,'model_settings',return_value=('test-only-secret','fixture')), patch.object(model,'reserve_call'), patch.object(model.httpx,'AsyncClient',return_value=client):
                with self.assertRaisesRegex(model.ModelUnavailable,'invalid structured output'):
                    await model.generate('malformed','planner',{},research.Plan)
        events = storage.rows('SELECT detail_json FROM run_events')
        self.assertNotIn('test-only-secret',json.dumps(events))


if __name__ == '__main__':
    unittest.main()
