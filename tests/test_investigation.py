import json
import unittest
from unittest.mock import patch, AsyncMock
from backend import investigation, research, storage
from backend.companies import resolve
from test_backend_audit import AuditFixture
from test_system import IsolatedDB
from backend.companies import Company
from backend.facts import validate_fact


class InvestigationTests(AuditFixture,unittest.IsolatedAsyncioTestCase):
    async def test_index_results_are_leads_not_source_facts(self):
        payload={'articles':[{'url':'https://independent.example/article','title':'Public source','seendate':'20261019T010000Z'}]}
        with patch.object(investigation.documents.Fetcher,'fetch',new=AsyncMock(return_value=(json.dumps(payload).encode(),'application/json','https://api.gdeltproject.org/'))),patch.object(investigation,'SEARCH_NEXT',0),patch.object(investigation,'SEARCH_BLOCKED_UNTIL',0),patch.object(investigation,'SEARCH_LOCK',__import__('asyncio').Lock()):
            result=await investigation.public_search('cash conversion','Demo Consumer Limited')
        self.assertEqual(result[0]['index_seen_at'],'20261019T010000Z')
        self.assertNotIn('publication_date',result[0])

    async def test_throttled_index_is_not_retried_or_treated_as_empty_coverage(self):
        with patch.object(investigation.documents.Fetcher,'fetch',new=AsyncMock(side_effect=ValueError('Source returned HTTP 429.'))) as fetch,patch.object(investigation,'SEARCH_NEXT',0),patch.object(investigation,'SEARCH_BLOCKED_UNTIL',0),patch.object(investigation,'SEARCH_LOCK',__import__('asyncio').Lock()):
            with self.assertRaises(ValueError):await investigation.public_search('cash conversion','Demo Consumer Limited')
            with self.assertRaisesRegex(ValueError,'backed off'):await investigation.public_search('revenue quality','Demo Consumer Limited')
            self.assertEqual(fetch.await_count,1)

    def candidate(self):
        s={'text':'Cash conversion diverges from the reported revenue trend.',
           'citations':[{'passage_id':1,'quote':'Revenue rose while cash conversion weakened.'},
                        {'passage_id':2,'quote':'Independent industry demand softened in June.'}]}
        analysis=research.Analysis(sufficient=True,discovery=s,significance=[s]*3,
            timeline=[{**s,'date':'2026-06-30'}],counterargument=s,
            falsification_condition='A comparable cash-flow recovery would weaken this interpretation.',limitations=[])
        review=research.Review(verdict='supported',counterargument=s,
            falsification_condition='A comparable cash-flow recovery would weaken this interpretation.',reasons=['Fixture only'])
        passages=[{'id':1,'document_id':1,'pdf_page':2,'company':'hul','sha256':'a','original_url':'https://www.hul.co.in/results','text':s['citations'][0]['quote']},
                  {'id':2,'document_id':2,'pdf_page':1,'company':'hul','sha256':'b','original_url':'https://independent.example/report','text':s['citations'][1]['quote']}]
        calculations=[{'id':1,'formula':'revenue_growth','value':'20','unit':'percent','inputs':[{'passage_id':1}]}]
        audit=[{'side':'challenge','local_passages':[2],'originals':[]}]
        return analysis,review,passages,calculations,audit

    async def test_hypothesis_and_alternative_drive_actual_queries(self):
        h=research.Hypothesis(question='Does cash conversion support reported growth?',alternative='Inventory investment explains the cash shortfall',search_terms='operating cash revenue')
        with patch.object(investigation.documents,'search',return_value=[]) as search,patch.object(investigation,'public_search',new=AsyncMock(return_value=[])) as public,patch.object(storage,'event'):
            _,audit,_=await investigation.collect(resolve('hul'),[h],None,True,'unused')
        self.assertTrue(any(c.args[1]==h.search_terms for c in search.call_args_list))
        self.assertTrue(any(c.args[1]==h.alternative for c in search.call_args_list))
        self.assertEqual(public.await_count,2)
        self.assertEqual([a['side'] for a in audit],['support','challenge'])

    async def test_discovery_requires_linked_math_dates_and_distinct_origins(self):
        args=self.candidate()
        gate=investigation.evidence_gate(*args)
        self.assertTrue(gate['admitted'])
        self.assertEqual(gate['rating'],'Moderate')
        self.assertNotEqual(gate['rating'],'Strong')
        args[2][1]['sha256']='a'
        self.assertFalse(investigation.evidence_gate(*args)['admitted'])

    async def test_two_company_documents_are_one_origin(self):
        args=self.candidate()
        args[2][1]['original_url']='https://www.hul.co.in/another-release'
        self.assertEqual(investigation.evidence_gate(*args)['distinct_content_origins'],1)

    async def test_credit_opinion_reusing_issuer_figures_is_not_second_financial_origin(self):
        args=self.candidate();args[2][1]['source_role']='External credit opinion; issuer financial information may be reused'
        gate=investigation.evidence_gate(*args)
        self.assertEqual(gate['distinct_content_origins'],1);self.assertFalse(gate['admitted'])

    async def test_regulator_is_a_distinct_candidate_origin_not_issuer_credit_data(self):
        args=self.candidate();args[2][1]['source_role']='Primary regulator order; investment impact not verified'
        self.assertEqual(investigation.evidence_gate(*args)['distinct_content_origins'],2)

    async def test_external_context_does_not_substitute_for_opposing_search(self):
        args=self.candidate()
        for item in args[4]:item['side']='context'
        self.assertFalse(investigation.evidence_gate(*args)['admitted'])

    async def test_missing_timeline_or_unlinked_calculation_prevents_admission(self):
        args=self.candidate()
        args[0].timeline=[]
        self.assertFalse(investigation.evidence_gate(*args)['admitted'])
        args=self.candidate()
        args[3][0]['inputs'].append({'passage_id':999})
        self.assertFalse(investigation.evidence_gate(*args)['admitted'])

    async def test_public_search_failure_is_recorded_without_inventing_evidence(self):
        h=research.Hypothesis(question='Does cash conversion support reported growth?',alternative='Inventory investment explains the cash shortfall',search_terms='operating cash revenue')
        with patch.object(investigation.documents,'search',return_value=[]),patch.object(investigation,'public_search',new=AsyncMock(side_effect=ValueError('Upstream restricted'))),patch.object(storage,'event'):
            rows,audit,_=await investigation.collect(resolve('hul'),[h],None,True,'unused')
        self.assertEqual(rows,[])
        self.assertTrue(all('unavailable' in a['coverage'] for a in audit))

    async def test_report_projects_all_eight_elements_without_raw_internal_errors(self):
        a,r,p,c,search=self.candidate()
        gate=investigation.evidence_gate(a,r,p,c,search)
        report={'investigation_version':2,'created_at':storage.now(),**a.model_dump(mode='json'),
                'passages':p,'discovery_checks':gate,'evidence_strength':{'rating':gate['rating'],'reasons':gate['reasons']},
                'limitations':['internal diagnostic not for website']}
        with patch.object(investigation,'latest_report',return_value=('fixture',report)):
            result=investigation.present('hul')
        for field in ('discovery','significance','timeline','calculations','counterargument','falsification_condition','evidence_strength'):
            self.assertTrue(result[field],field)
        self.assertTrue(result['discovery']['citations'][0]['url'].startswith('/documents/'))
        self.assertNotIn('internal diagnostic',json.dumps(result))


class GeneralityTests(IsolatedDB,unittest.IsolatedAsyncioTestCase):
    async def test_new_company_runs_without_case_configuration(self):
        # Synthetic positive path, not evidence of a real-company discovery.
        profile=Company(id='new-consumer',legal_name='New Consumer Limited',business_model='consumer',domains=['example.com'],seeds=['https://example.com/investors'])
        current=self.fact()
        prior=self.fact('100','2024-04-01','2025-03-31')
        with storage.database() as db:
            db.execute('INSERT INTO companies VALUES(?,?,?,?)',(profile.id,profile.legal_name,profile.business_model,profile.model_dump_json()))
            db.execute('UPDATE documents SET company=?',(profile.id,))
            db.execute("UPDATE documents SET original_url='https://example.com/current' WHERE id=(SELECT document_id FROM passages WHERE id=?)",(current.passage_id,))
            db.execute("UPDATE documents SET original_url='https://independent.example/prior' WHERE id=(SELECT document_id FROM passages WHERE id=?)",(prior.passage_id,))
        validate_fact(current,profile.id)
        validate_fact(prior,profile.id)
        citations=[{'passage_id':f.passage_id,'excerpt_id':0} for f in (current,prior)]
        s={'text':'Synthetic revenue relationship requires comparison and challenge.','citations':citations}
        plan=research.Plan(hypotheses=[{'question':'Does revenue growth survive comparison on the same basis?', 'alternative':'Revenue growth reflects a changed revenue definition','search_terms':'revenue operations'}])
        analysis=research.Analysis(sufficient=True,discovery=s,significance=[s]*3,timeline=[{'date':'2026-03-31',**s}],counterargument=s,
            falsification_condition='A restatement changing the comparative revenue basis would invalidate this fixture.',limitations=['Synthetic fixture only.'])
        review=research.Review(verdict='supported',counterargument=s,falsification_condition=analysis.falsification_condition,reasons=['Synthetic fixture only.'])
        with patch.object(research,'generate',new=AsyncMock(side_effect=[plan,research.Extracted(facts=[]),analysis,review])):
            run_id=research.create_run(research.RunRequest(company=profile.id,refresh=False))
            await research.execute(run_id)
        report=json.loads(storage.rows('SELECT report_json FROM research_runs WHERE id=?',(run_id,))[0]['report_json'])
        self.assertEqual(report['status'],'completed')
        self.assertTrue(report['discovery_checks']['admitted'])
        self.assertFalse((self.root/'config/company_cases/new-consumer.json').exists())
        self.assertEqual(investigation.present(profile.id)['status'],'supported_candidate')
