import unittest
import httpx
from unittest.mock import patch,AsyncMock
from backend import research_gaps as g
from backend import companies

def history(scope='consolidated',days=365):
    return {'periods':[{'label':'FY2025','scope':'consolidated','duration_days':365},
                       {'label':'FY2026','scope':scope,'duration_days':days}],
            'excel_diagnostics':[{'cash_conversion':1.14,'cash_after_capex_crore':2115.8,'ebitda_margin':.178,'revenue_growth':.07},
                                 {'cash_conversion':1.03,'cash_after_capex_crore':2406,'ebitda_margin':.185,'revenue_growth':.067}]}

class GapTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # These tests must not depend on a developer's private company registry.
        britannia=companies.Company(id='britannia',legal_name='Britannia Industries Limited',
            business_model='fmcg',domains=['britannia.co.in'],
            seeds=['https://www.britannia.co.in/'])
        registry={p.id:p for p in [*companies.PROFILES,britannia]}
        self.registry_patch=patch.object(companies,'profiles',return_value=registry)
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)

    def test_cash_signal_not_a_causal_or_investment_verdict(self):
        signals=g.signals(history());s=signals[0]
        self.assertIn('weaker cash',s['title']);self.assertIn('unconfirmed',s['status'])
        self.assertTrue(s['alternative'] and s['falsification'] and s['investor_use'])
        self.assertEqual(s['comparison'][1]['cash_conversion'],1.03)

    def test_one_confirmed_discovery_does_not_complete_missing_sector_work(self):
        p={'research':{'status':'completed','discovery_checks':{'admitted':True}},'valuation':{'weighted':{}},'news':{'status':'assessed'}}
        c=g.report_coverage(p);self.assertFalse(c['complete'])
        self.assertTrue(next(a for a in c['areas'] if a['area']=='Corroborated discovery')['covered'])
        self.assertFalse(next(a for a in c['areas'] if a['area']=='Management and governance')['covered'])

    def test_no_scope_or_fifteen_month_comparisons(self):
        self.assertEqual(g.signals(history(scope='continuing')),[])
        self.assertEqual(g.signals(history(days=456)),[])

    def test_no_missing_values_as_zero_or_fake_observations(self):
        h=history();h['excel_diagnostics']=[{},{}]
        self.assertEqual(g.signals(h),[])
        self.assertFalse(g.numeric(float('nan')));self.assertFalse(g.numeric(True))

    def test_keyword_hit_is_not_an_answer(self):
        row={'text':'Volume and pricing remain uncertain.','document_id':8,'id':90,'pdf_page':4,'title':'Company results'}
        d=g.local_dossier({'history':history()},[row])
        topic=d['topics'][0];self.assertEqual(len(topic['excerpts']),1)
        self.assertIn('corroboration required',topic['status'])
        self.assertEqual(topic['excerpts'][0]['url'],'/documents/8/original#page=4')
        self.assertIsNone(topic['excerpts'][0]['publication_date'])
        self.assertIn('No sufficiently',d['topics'][5]['status'])

    def test_accounting_boilerplate_and_undated_growth_are_not_operating_answers(self):
        rows=[{'text':'Expected credit losses and fair value hierarchy consider cash flows and receivables.', 'document_id':8,'id':90,'pdf_page':4},
              {'text':'We expect growth and expansion to benefit the company.', 'document_id':8,'id':91,'pdf_page':5}]
        d=g.local_dossier({'history':history()},rows)
        self.assertFalse(d['topics'][2]['excerpts']);self.assertFalse(d['topics'][6]['excerpts'])

    async def test_provider_independent_search_failures_remain_visible(self):
        with patch.object(g.investigation,'prepared_passages',return_value=([],{'signature':'hash'})),patch.object(g,'search_with_fallback',new=AsyncMock(side_effect=ValueError('upstream unavailable'))) as search:
            d=await g.investigate({'company_id':'britannia','history':history()})
        self.assertEqual(search.await_count,4)
        self.assertTrue(all('gap remains' in a['status'] for a in d['retrieval_audit']))
        self.assertTrue(d['unresolved']);self.assertEqual(len(d['topics']),8)

    def test_rss_rejects_entities_and_non_https_credentials(self):
        with self.assertRaises(ValueError):g.parse_search_rss(b'<!DOCTYPE rss><rss/>')
        hits=g.parse_search_rss(b'<rss><channel><item><link>http://example.org</link></item><item><link>https://u:p@example.org</link></item><item><link>https://example.org/a</link><title>Lead</title></item><item><link>https://example.org/a</link></item></channel></rss>')
        self.assertEqual(hits,[{'url':'https://example.org/a','title':'Lead'}])

    def test_short_company_names_are_retrievable_without_generic_india_matches(self):
        self.assertTrue(g.subject_matches('ITC reported operating cash flow.',g.resolve('itc')))
        self.assertFalse(g.subject_matches('Switch cash in India',g.resolve('itc')))
        self.assertFalse(g.subject_matches('India consumer volumes',g.resolve('nestle-india')))

    def test_group_brand_and_generic_words_do_not_identify_the_issuer(self):
        self.assertFalse(g.subject_matches('Tata Motors sells consumer products and discusses cash flow.',g.resolve('tata-consumer')))
        self.assertTrue(g.subject_matches('Tata Consumer Products Limited reported cash flow.',g.resolve('tata-consumer')))
        self.assertTrue(g.subject_matches('Nestlé India Limited reported results.',g.resolve('nestle-india')))
        self.assertFalse(g.subject_matches('Nestlé S.A. discusses India demand.',g.resolve('nestle-india')))

    async def test_free_rss_fallback_after_first_provider_failure(self):
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'<rss><channel><item><link>https://example.org/original</link><title>Original lead</title></item></channel></rss>')))
        audit={}
        with patch.object(g.investigation,'public_search',new=AsyncMock(side_effect=ValueError('unavailable'))),patch.object(g.httpx,'AsyncClient',return_value=client):
            hits=await g.search_with_fallback('cash flow','Britannia',audit)
        self.assertEqual(hits[0]['url'],'https://example.org/original')
        self.assertEqual([p['provider'] for p in audit['search_providers']],['GDELT','Bing public RSS'])

    async def test_invalid_compact_pack_does_not_fall_back_to_old_narrative(self):
        with patch.object(g.investigation,'prepared_passages',side_effect=ValueError('hash mismatch')),patch.object(g.investigation,'public_search',new=AsyncMock()) as search:
            d=await g.investigate({'company_id':'britannia','history':history()})
        search.assert_not_awaited();self.assertFalse(d['topics']);self.assertIn('could not be validated',d['unresolved'][0])
