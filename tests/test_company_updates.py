import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch, AsyncMock
from backend import storage, company_updates as updates, news_feeds, model, excel_engine
from backend.companies import Company


class OnlineUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        project = storage.PROJECT_DIR
        self.patches = [patch.object(storage,'DB_PATH',self.root/'test.sqlite')]
        self.patches[0].start()
        with storage.database() as db:
            db.executescript(storage.SCHEMA)
            for schema in (project/'schemas').glob('*.sql'):
                db.executescript(schema.read_text())
        self.patches.append(patch.object(storage,'PROJECT_DIR',self.root))
        self.patches[-1].start()
        self.patches.append(patch.object(news_feeds,'primary_evidence',new=AsyncMock(return_value={'sources':[],'blocks':[],'coverage':[]})))
        self.patches[-1].start()
        (self.root/'config').mkdir()
        (self.root/'config/online_research.json').write_text(json.dumps({'search_mode':'gemini_free_grounding'}))
        self.profile = Company(id='demo',legal_name='Demo Foods Limited',business_model='fmcg',
                               domains=['example.com'],seeds=['https://example.com/investors'])
        with storage.database() as db:
            db.execute('INSERT INTO companies VALUES(?,?,?,?)',('demo',self.profile.legal_name,'fmcg',self.profile.model_dump_json()))

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def candidate(self):
        quote = 'A change in palm oil supply was reported; original announcement verification is required.'
        return {'content':{'parts':[{'text':quote}]},'groundingMetadata':{
            'webSearchQueries':['Demo Foods input costs latest'],
            'groundingChunks':[{'web':{'uri':'https://example.com/news','title':'Dated news source'}}],
            'groundingSupports':[{'segment':{'text':quote},'groundingChunkIndices':[0]}]}}

    def assessment(self, **changes):
        event = {'headline':'Reported input-supply development requires review','category':'industry_commodities',
            'event_date':None,'publication_date':None,'date_evidence':'',
            'evidence':[{'block_id':1,'quote':'A change in palm oil supply was reported'}],
            'relevance':'If the company uses palm oil, delivered input costs may change.',
            'exposure_basis':'documented_in_local_pack','local_exposure_quote':'Company sourcing includes palm oil in its raw materials.',
            'mechanism':'A possible supply change could affect costs with inventory and pricing lags.',
            'direction':'uncertain','horizon':'near_term','confidence':'medium',
            'drivers_to_review':['ebitda_margin','price_mix_growth'],
            'review_action':'Verify actual delivered costs before editing the margin forecast.',
            'baseline_overlap_quote':'','falsification':'Check whether procurement costs and volume exposure remain unchanged.',**changes}
        return updates.Assessment(summary='Search evidence requires source and financial review.',events=[event],
                                  coverage_gaps=['Source publication dates and company-specific exposures remain unverified.'])

    def test_ungrounded_model_memory_is_not_news(self):
        with self.assertRaises(model.ModelUnavailable):
            updates.parse_grounding({'content':{'parts':[{'text':'Unsourced news claim'}]},'groundingMetadata':{}})
        candidate = self.candidate()
        candidate['groundingMetadata']['groundingSupports'][0]['segment']['text'] = 'Invented source text'
        with self.assertRaises(model.ModelUnavailable):
            updates.parse_grounding(candidate)

    def test_each_valuation_attempts_a_new_check_even_on_the_same_day(self):
        with patch.object(updates,'execute',new=AsyncMock(return_value={'status':'partial'})) as execute:
            async def twice():
                await updates.for_valuation('demo')
                with storage.database() as db:
                    db.execute("UPDATE company_update_runs SET status='partial'")
                    db.execute("UPDATE research_runs SET status='partial'")
                await updates.for_valuation('demo')
            asyncio.run(twice())
        self.assertEqual(execute.await_count,2)
        self.assertNotEqual(execute.await_args_list[0].args,execute.await_args_list[1].args)

    def test_original_company_statement_is_not_labelled_a_verified_news_article(self):
        grounded=updates.parse_grounding(self.candidate())
        grounded['source_kind']='primary_pages_and_news_headlines'
        grounded['sources'][0]['source_kind']='primary_company_disclosure'
        events,_=updates.validate_assessment(self.assessment(),grounded,'')
        self.assertEqual(events[0]['fact_status'],'company_disclosure_not_independently_corroborated')

    def test_original_news_article_does_not_become_a_regulator_verified_fact(self):
        grounded=updates.parse_grounding(self.candidate())
        grounded['source_kind']='primary_pages_and_news_headlines'
        grounded['sources'][0]['source_kind']='original_news_article'
        events,_=updates.validate_assessment(self.assessment(),grounded,'')
        self.assertEqual(events[0]['fact_status'],'original_report_underlying_claim_not_independently_verified')

    def test_regulator_document_does_not_verify_investment_impact(self):
        grounded=updates.parse_grounding(self.candidate())
        grounded['sources'][0]['source_kind']='primary_regulatory_document'
        events,rejected=updates.validate_assessment(self.assessment(),grounded,'Company sourcing includes palm oil in its raw materials.')
        self.assertFalse(rejected)
        self.assertEqual(events[0]['fact_status'],'regulator_document_retrieved_impact_and_appeal_status_not_verified')
        self.assertIn('no automatic numerical change',events[0]['quantitative_treatment'])

    def test_commodity_queries_follow_company_disclosures(self):
        profile=Company(id='beverages',legal_name='Beverages Limited',business_model='fmcg',domains=['example.com'],seeds=['https://example.com/results'])
        queries=dict(news_feeds.queries(profile,'Coffee coffee coffee and tea tea, with packaging and freight.'))
        self.assertIn('coffee',queries['industry_commodities'])
        self.assertIn('tea',queries['geopolitical'])
        self.assertNotIn('palm oil',queries['industry_commodities'])

    def test_fabricated_citation_and_future_occurrence_rejected(self):
        grounded = updates.parse_grounding(self.candidate())
        wrong = self.assessment(evidence=[{'block_id':1,'quote':'An invented quantitative forecast supposedly from the source'}])
        self.assertFalse(updates.validate_assessment(wrong,grounded,'')[0])
        future = self.assessment(event_date=storage.today_ist()+timedelta(days=1))
        self.assertFalse(updates.validate_assessment(future,grounded,'')[0])

    def test_exposure_and_dates_are_not_invented(self):
        grounded = updates.parse_grounding(self.candidate())
        assessment = self.assessment(event_date=storage.today_ist(), date_evidence='An invented source date')
        events, _ = updates.validate_assessment(assessment,grounded,'Unrelated local evidence')
        self.assertIsNone(events[0]['event_date'])
        self.assertEqual(events[0]['confidence'],'low')
        self.assertEqual(events[0]['exposure_basis'],'possible_exposure_requires_verification')
        self.assertEqual(events[0]['fact_status'],'search_grounded_not_independently_verified')

    def test_tracking_does_not_claim_novelty(self):
        grounded = updates.parse_grounding(self.candidate())
        one, _ = updates.validate_assessment(self.assessment(),grounded,'')
        two, _ = updates.validate_assessment(self.assessment(),grounded,'',one)
        self.assertEqual(two[0]['novelty'],'previously_tracked')
        self.assertIn('requires_review',one[0]['novelty'])

    def test_invalid_event_does_not_erase_a_valid_sibling_or_get_repaired(self):
        data=self.assessment().model_dump(mode='json')
        bad=json.loads(json.dumps(data['events'][0]))
        bad['evidence'][0]['block_id']=0
        data['events'].append(bad)
        result=model.validated_response('updates',updates.Assessment,json.dumps(data))
        self.assertEqual(len(result.events),1)
        self.assertEqual(result.events[0].evidence[0].block_id,1)
        self.assertIn('rejected',result.coverage_gaps[0])

    def test_public_feed_assessment_is_always_labelled_unverified(self):
        (self.root/'config/online_research.json').write_text(json.dumps({'search_mode':'public_news_feeds'}))
        lead = {'lead_id':'fixture','headline':'A change in palm oil supply was reported; verification required.',
                'published_at':storage.now(),'url':'https://news.google.com/rss/articles/fixture',
                'verification':'unverified headline',**news_feeds.conditional_impact('industry_commodities')}
        refresh_id, _ = updates.create('demo')
        with patch.object(updates.evidence_packs,'source_fingerprints',return_value={}), \
             patch.object(news_feeds,'discover',new=AsyncMock(return_value=([lead],[{'query':'fixture','status':'feed_read'}]))), \
             patch.object(model,'grounded_search',new=AsyncMock(side_effect=AssertionError('must not call unavailable search model'))), \
             patch.object(model,'generate',new=AsyncMock(return_value=self.assessment())):
            result = asyncio.run(updates.execute(refresh_id))
        self.assertEqual(result['status'],'assessed_with_unverified_sources')
        self.assertEqual(result['events'][0]['fact_status'],'unverified_headline_claim')
        self.assertEqual(result['events'][0]['confidence'],'low')

    def test_feed_rejects_future_dates_xml_entities_and_unsafe_links(self):
        from email.utils import format_datetime
        from datetime import datetime, timezone
        future = format_datetime(datetime.now(timezone.utc)+timedelta(days=2))
        xml = f'<rss><channel><item><title>Future claim</title><pubDate>{future}</pubDate><link>https://news.google.com/rss/articles/test</link></item></channel></rss>'.encode()
        self.assertEqual(news_feeds.parse_feed(xml,'company'),[])
        with self.assertRaises(ValueError):
            news_feeds.parse_feed(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///private">]><rss/>','company')
        self.assertFalse(updates._https('https://127.0.0.1/private'))
        self.assertFalse(updates._https('https://name:password@example.com/private'))

    def test_two_call_exception_is_scoped_and_cannot_be_extended(self):
        first, _ = updates.create('demo')
        with storage.database() as db:
            db.execute('UPDATE research_runs SET model_calls=? WHERE id=?',(model.DAILY_REQUEST_LIMIT,first))
            db.execute("UPDATE research_runs SET status='partial' WHERE id=?",(first,))
            db.execute("UPDATE company_update_runs SET status='partial' WHERE id=?",(first,))
        second, _ = updates.create('demo')
        model.grant_two_calls(second,'Explicit test approval for exactly two additional free-tier requests.')
        model.reserve_call(second)
        model.reserve_call(second)
        with self.assertRaises(model.ModelUnavailable):
            model.reserve_call(second)
        with self.assertRaises(ValueError):
            model.grant_two_calls(first,'A second exception must be rejected by the daily guard.')
        self.assertEqual(storage.rows('SELECT remaining_calls FROM model_call_grants WHERE run_id=?',(second,))[0]['remaining_calls'],0)

    def test_evidence_context_spans_all_original_documents(self):
        pages = [{'source_file':source,'original_page':n,'text':'Documented volume and margin source text '+str(n)}
                 for source in ('old-report.pdf','recent-call.pdf','current-deck.pdf') for n in range(1,21)]
        excerpts = updates.local_excerpts(pages)
        self.assertEqual({p['source'] for p in excerpts},{'old-report.pdf','recent-call.pdf','current-deck.pdf'})
        self.assertLessEqual(len(excerpts),45)

    def test_cutoff_uses_indian_date_at_utc_midnight_boundary(self):
        from datetime import date
        row = {'id':'fixture','status':'assessed','checked_at':'2026-10-18T23:00:00+00:00',
               'result':{'events':[], 'news_leads':[]}}
        with patch.object(updates,'latest',return_value=row):
            self.assertEqual(updates.context('demo',date(2026,10,18))['status'],'excluded_after_cutoff')
            self.assertEqual(updates.context('demo',date(2026,10,19))['status'],'assessed')

    def test_feed_failure_is_visible_even_when_model_fails(self):
        refresh_id, _ = updates.create('demo')
        discovery = ([{'lead_id':'fixture','headline':'Unverified dated news lead'}],
                     [{'category':'company','status':'feed_read','leads':1}])
        with patch.object(updates.evidence_packs,'source_fingerprints',return_value={}), \
             patch.object(news_feeds,'discover',new=AsyncMock(return_value=discovery)), \
             patch.object(model,'grounded_search',new=AsyncMock(side_effect=model.ModelUnavailable('Daily limit reached.'))):
            result = asyncio.run(updates.execute(refresh_id))
        self.assertEqual(result['status'],'partial')
        self.assertEqual(len(result['news_leads']),1)
        self.assertTrue(any('Daily limit' in gap for gap in result['limitations']))
        self.assertEqual(storage.rows('SELECT COUNT(*) AS n FROM assumption_changes')[0]['n'],0)
        self.assertEqual(storage.rows('SELECT COUNT(*) AS n FROM library_records')[0]['n'],0)

    def test_mocked_grounded_pipeline_retains_sources_and_excel_review_context(self):
        refresh_id, _ = updates.create('demo')
        with patch.object(updates.evidence_packs,'source_fingerprints',return_value={}), \
             patch.object(news_feeds,'discover',new=AsyncMock(return_value=([],[]))), \
             patch.object(model,'grounded_search',new=AsyncMock(return_value=self.candidate())), \
             patch.object(model,'generate',new=AsyncMock(return_value=self.assessment())), \
             patch.object(excel_engine.library,'inventory',return_value={'source_folder':'fixture','files':[]}), \
             patch.object(excel_engine.library,'root_folder',return_value=self.root):
            result = asyncio.run(updates.execute(refresh_id))
            package = excel_engine.company_package('demo')
        self.assertEqual(result['status'],'assessed')
        self.assertEqual(len(result['sources']),1)
        self.assertTrue(any('Online event' in n['topic'] for n in package['research_notes']))
        self.assertTrue(any('Online refresh' in issue for issue in package['issues']))
        self.assertEqual(package['assumptions'],[])
        self.assertEqual(updates.context('demo',storage.today_ist()-timedelta(days=1))['status'],'excluded_after_cutoff')
