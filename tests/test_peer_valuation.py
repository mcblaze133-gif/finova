import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from backend import peer_valuation as p,public_sources,research
from backend import news_feeds


def review():
    def company(name):
        return {'company_id':name,'company':name,'period_start':'2025-04-01','period_end':'2026-03-31',
                'price_date':'2026-10-23','accounting_scope':'consolidated','owner_allocation':1.,
                'values':{'market_cap':100,'revenue':10},'evidence':[{'document_id':1}]}
    return {'price_date':'2026-10-23','reviewed_at':'2026-10-24','companies':[company('hul'),company('dabur')],
            'policies':{'hul':{'included':{'dabur':'Adjacent category'},'rationale':'Conditional comparison'}}}


class PeerTests(unittest.TestCase):
    def build(self,data):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'data').mkdir();(root/'data/peer-reviews.json').write_text(json.dumps(data))
            with patch.object(p.storage,'PROJECT_DIR',root),patch.object(p,'evidence',return_value={'checked':True}):
                return p.build('hul')

    def test_subject_excluded_and_review_not_an_attestation(self):
        out=self.build(review())
        self.assertFalse(out['companies'][0]['included']);self.assertTrue(out['companies'][1]['included'])
        self.assertIn('analyst estimate',out['meaning'])

    def test_rejects_incompatible_inputs(self):
        for key,value in [('period_start','2025-04-02'),('period_end','2026-03-30'),
                          ('price_date','2026-10-22'),('accounting_scope','standalone'),('owner_allocation',1.01)]:
            data=review();data['companies'][1][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.build(data)

    def test_rejects_self_unknown_and_duplicate_peers(self):
        for selected in [{'hul':'self'},{'missing':'unknown'}]:
            data=review();data['policies']['hul']['included']=selected
            with self.assertRaises(ValueError):self.build(data)
        data=review();data['companies'].append(copy.deepcopy(data['companies'][1]))
        with self.assertRaises(ValueError):self.build(data)

    def test_nan_is_not_a_missing_value(self):
        data=review();data['companies'][1]['values']['debt']=float('nan')
        with self.assertRaises(ValueError):self.build(data)

    def test_stale_pre_bonus_share_count_rejected(self):
        data=review();data['companies'][0]['values'].update(market_cap=100000000,price=100,shares=500000)
        with self.assertRaises(ValueError):self.build(data)
        data['companies'][0]['values']['shares']=1000000
        self.assertTrue(self.build(data)['companies'][0]['subject'])

    def test_external_source_roles_survive_model_context(self):
        item={'id':1,'document_id':2,'pdf_page':1,'text':'Externally authored opinion.',
              'original_url':'https://example.com/report','publisher':'Rating agency',
              'source_role':'Issuer figures reused, external credit opinion'}
        out=research.excerpt_context(research.safe_passages([item]))[0]
        self.assertEqual(out['source_role'],item['source_role'])

    def test_changed_archive_or_quotation_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'data/raw';raw.mkdir(parents=True);file=raw/'original.html'
            file.write_bytes(b'Original file');digest=hashlib.sha256(file.read_bytes()).hexdigest()
            row={'id':1,'local_path':'data/raw/original.html','sha256':digest,'text':'Exact reported passage',
                 'pdf_page':1,'title':'Original','original_url':'https://example.com/original'}
            ref={'document_id':1,'page':1,'sha256':digest,'quote':'Exact reported passage'}
            with patch.object(p.storage,'PROJECT_DIR',root),patch.object(p.storage,'DATA_DIR',root/'data'),patch.object(p.storage,'rows',return_value=[row]):
                self.assertEqual(p.evidence(ref)['sha256'],digest)
                with self.assertRaises(ValueError):p.evidence(ref|{'quote':'Fabricated text'})
                file.write_bytes(b'Changed file')
                with self.assertRaises(ValueError):p.evidence(ref)


class PublicRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_reviewed_regulator_is_not_mislabelled_company_disclosure(self):
        url='https://ccpa.doca.gov.in/order.pdf'
        class Fetcher:
            receipts=[]
            def __init__(self,*args):pass
            async def fetch(self,*args):return b'%PDF-source','application/pdf',url
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config').mkdir();out=root/'out';out.mkdir()
            (root/'config/public_source_watchlist.json').write_text(json.dumps({'demo':[{'url':url,'title':'Regulatory order','kind':'regulatory'}]}))
            with patch.object(p.storage,'PROJECT_DIR',root),patch.object(public_sources.documents,'Fetcher',Fetcher),patch.object(public_sources,'reviewed_pages',return_value=['Visually reviewed regulatory operative passage with enough source text for the bounded model catalog.']):
                result=await news_feeds.primary_evidence(SimpleNamespace(id='demo',domains=['example.com'],seeds=[]),out)
            self.assertEqual(result['sources'][0]['source_kind'],'primary_regulatory_document')
            self.assertIn('manual',result['sources'][0]['verification'])
            self.assertIn('regulator',result['blocks'][0]['text'])

    def test_visual_transcript_requires_identical_original_and_url(self):
        raw=b'%PDF-reviewed-scanned-source';digest=hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'reviewed-transcripts';folder.mkdir()
            record={'sha256':digest,'url':'https://example.com/order.pdf','method':'manual-visual-transcription',
                    'pages':['Visually reviewed passage']}
            record['pages_sha256']=hashlib.sha256(json.dumps(record['pages'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            (folder/(digest+'.json')).write_text(json.dumps(record))
            with patch.object(public_sources.storage,'DATA_DIR',root):
                self.assertEqual(public_sources.reviewed_pages(raw,record['url']),record['pages'])
                self.assertIsNone(public_sources.reviewed_pages(raw+b' changed',record['url']))
                with self.assertRaises(ValueError):public_sources.reviewed_pages(raw,'https://other.example/order.pdf')
                record['pages']=['Edited unreviewed statement']
                (folder/(digest+'.json')).write_text(json.dumps(record))
                with self.assertRaises(ValueError):public_sources.reviewed_pages(raw,record['url'])

    async def test_live_failure_does_not_reuse_stored_report(self):
        source={'url':'https://example.com/report','title':'Report','publication_date':'2026-10-01',
                'publisher':'Agency','role':'External opinion'}
        class FailedFetcher:
            def __init__(self,*args):pass
            async def fetch(self,*args):raise TimeoutError()
        with patch.object(public_sources,'registry',return_value=[source]),patch.object(public_sources.documents,'Fetcher',FailedFetcher):
            result=await public_sources.refresh('hul','2026-10-23')
        self.assertEqual(result['sources'][0]['status'],'unavailable')
        self.assertEqual(public_sources.passages(result,'market competition'),[])

    async def test_future_source_excluded_without_request(self):
        source={'url':'https://example.com/report','title':'Report','publication_date':'2026-10-24',
                'publisher':'Agency','role':'External opinion'}
        with patch.object(public_sources,'registry',return_value=[source]),patch.object(public_sources.documents,'Fetcher') as fetch:
            result=await public_sources.refresh('hul','2026-10-23')
        fetch.assert_not_called();self.assertEqual(result['sources'][0]['status'],'excluded_after_cutoff')
