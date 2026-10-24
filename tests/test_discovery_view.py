import unittest
from unittest.mock import patch
import httpx
from backend import discovery_view as view, analysis_reports as ar
from backend.main import app


def fixture():
    statement={'text':'Margins improved; persistence requires investigation.',
               'citations':[{'passage_id':1,'quote':'Reported margin improved to 20 percent.'}]}
    return {'report_id':'a'*32,'company_id':'hul','company':'HUL','history':{},
        'research':{'passages':[{'id':1,'document_id':2,'pdf_page':7,'company':'hul',
            'text':'Reported margin improved to 20 percent. Other evidence.',
            'title':'Annual results','original_url':'https://www.hul.co.in/results.pdf'}],
            'candidate_discovery':statement,'sector_sections':[{'topic':'Costs and profitability',
                'statements':[statement],'investor_use':'Compare costs over a full cycle.'}]}}


class DiscoveryViewTests(unittest.TestCase):
    def test_section_excerpt_is_not_lost_when_discovery_uses_another_page_window(self):
        data=fixture();original=data['research']['passages'][0].copy()
        data['research']['section_analysis']={'passage_catalog':[original]}
        data['research']['passages'][0]['text']='Different exact window from the same source page.'
        result=view.build(data)
        self.assertEqual(len(result['cards']),1);self.assertEqual(len(result['business']),1)

    def test_conflicting_document_identity_for_one_passage_fails_closed(self):
        data=fixture();other=data['research']['passages'][0]|{'document_id':99}
        data['research']['section_analysis']={'passage_catalog':[other]}
        result=view.build(data)
        self.assertEqual(result['cards'],[]);self.assertEqual(result['business'],[])

    def test_every_published_claim_has_a_page_link_and_explicit_verification(self):
        data=view.build(fixture())
        self.assertEqual(len(data['cards']),1)
        for card in data['cards']+data['business']:
            self.assertFalse(card['verified'])
            self.assertTrue(card['verification_label'])
            self.assertEqual(card['sources'][0]['url'],'/documents/2/original#page=7')
        self.assertEqual(data['verified_discoveries'],0)

    def test_unknown_passage_or_changed_quotation_suppresses_claim(self):
        for change in ('id','quote'):
            p=fixture()
            for item in [p['research']['candidate_discovery'],*p['research']['sector_sections'][0]['statements']]:
                item['citations'][0].update({'passage_id':99} if change=='id' else {'quote':'Invented claim'})
            d=view.build(p)
            self.assertFalse(d['cards']);self.assertFalse(d['business'])
            self.assertGreater(d['omitted_unlinked_claims'],0)

    def test_gate_admission_does_not_become_unqualified_verification(self):
        p=fixture();p['research']['discovery_checks']={'admitted':True}
        p['research']['discovery']=p['research'].pop('candidate_discovery')
        d=view.build(p)
        self.assertFalse(d['cards'][0]['verified'])
        self.assertIn('independent review pending',d['cards'][0]['verification_label'])

    def test_unsafe_source_links_never_leave_the_endpoint(self):
        for url in ('javascript:alert(1)','https://user:password@example.com/a','http://example.com/', '//example.com/'):
            self.assertIsNone(view.safe_url(url))
        p=fixture();p['news']={'result':{'sources':[{'source_id':1,'url':'javascript:alert(1)'}],
            'events':[{'headline':'Unsafe source','source_ids':[1]}]}}
        self.assertFalse(view.build(p)['updates'])

    def test_absent_evidence_stays_empty_instead_of_reusing_another_company(self):
        self.assertFalse(view.build({'report_id':'b'*32,'company_id':'itc'})['cards'])

    def test_two_growth_rates_link_all_three_revenue_periods(self):
        p=fixture();p['history']={'periods':[], 'excel_diagnostics':[]}
        for i,year in enumerate((2024,2025,2026),1):
            p['history']['periods'].append({'label':str(year),'end':f'{year}-03-31',
                'scope':'consolidated total','duration_days':365,
                'sources':{'revenue':[{'url':f'/documents/{i}/original#page=2','pages':'2','file':f'{year}.pdf'}]}})
            p['history']['excel_diagnostics'].append({'revenue_growth':.1})
        d=view.build(p);card=next(c for c in d['cards'] if c['kind']=='observation')
        self.assertEqual({s['url'] for s in card['sources']},
                         {f'/documents/{i}/original#page=2' for i in (1,2,3)})


class DiscoveryEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_requested_frozen_report_can_supply_findings(self):
        import json
        p=fixture();job={'company':'hul','status':'partial','snapshot_json':json.dumps(p)}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            with patch.object(ar,'row',return_value=job):
                r=await client.get('/analysis-reports/'+'a'*32+'/findings')
                self.assertEqual(r.status_code,200);self.assertEqual(r.json()['report_id'],'a'*32)
                r=await client.get('/analysis-reports/'+'b'*32+'/findings')
                self.assertEqual(r.status_code,409)

    async def test_running_report_has_no_earlier_findings_fallback(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            with patch.object(ar,'row',return_value={'status':'running','snapshot_json':None}):
                r=await client.get('/analysis-reports/'+'a'*32+'/findings')
                self.assertEqual(r.status_code,409)
