import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from urllib.robotparser import RobotFileParser
import httpx
from backend import documents, source_cache, storage

URL='https://example.com/investors/results.html'
BODY=b'<html><p>'+b'Reported operating performance and cash flow evidence. '*8+b'</p></html>'


class SourceCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db=patch.object(storage,'DB_PATH',Path(self.temp.name)/'local.sqlite')
        db.start();self.addCleanup(db.stop)

    async def fetch(self,handler,url=URL,limit=documents.MAX_BYTES,policy=None):
        original=httpx.AsyncClient
        client=original(transport=httpx.MockTransport(handler))
        f=documents.Fetcher(['example.com'])
        with patch.object(documents,'public_host',new=AsyncMock()),patch.object(documents.httpx,'AsyncClient',return_value=client):
            result=await f.raw(url,limit,access_policy=policy)
        return result,f

    async def test_live_conditional_request_and_304_preserve_exact_body(self):
        await self.fetch(lambda r:httpx.Response(200,content=BODY,headers={'etag':'"v1"','content-type':'text/html'}))
        def unchanged(request):
            self.assertEqual(request.headers['if-none-match'],'"v1"')
            return httpx.Response(304)
        result,f=await self.fetch(unchanged)
        self.assertEqual(result,(BODY,'text/html',URL))
        self.assertEqual(f.requests,1)
        self.assertTrue(f.receipts[0]['body_reused'])
        self.assertEqual(f.receipts[0]['http_status'],304)

    async def test_failure_never_falls_back_to_previous_content(self):
        source_cache.store(URL,BODY,'text/html',{'etag':'v1'})
        with self.assertRaisesRegex(ValueError,'HTTP 503'):
            await self.fetch(lambda r:httpx.Response(503))

    async def test_changed_body_replaces_validator_and_content(self):
        source_cache.store(URL,BODY,'text/html',{'etag':'v1'})
        new=BODY+b'Newly published information.'
        result,f=await self.fetch(lambda r:httpx.Response(200,content=new,headers={'etag':'v2','content-type':'text/html'}))
        self.assertEqual(result[0],new)
        self.assertFalse(f.receipts[0]['body_reused'])
        self.assertEqual(source_cache.load(URL,documents.MAX_BYTES)['etag'],'v2')

    async def test_corrupt_body_is_not_sent_as_a_valid_cache(self):
        source_cache.store(URL,BODY,'text/html',{'etag':'v1'})
        (source_cache.root()/'bodies'/source_cache.digest(BODY)).write_bytes(b'corrupted')
        def response(request):
            self.assertNotIn('if-none-match',request.headers)
            return httpx.Response(304)
        with self.assertRaisesRegex(ValueError,'without a verified cached body'):
            await self.fetch(response)

    async def test_no_store_and_unconditional_304_are_rejected(self):
        source_cache.store(URL,BODY,'text/html',{'etag':'v1'})
        await self.fetch(lambda r:httpx.Response(200,content=BODY,headers={'etag':'v2','cache-control':'no-store','content-type':'text/html'}))
        self.assertIsNone(source_cache.load(URL,documents.MAX_BYTES))
        with self.assertRaisesRegex(ValueError,'without a verified cached body'):
            await self.fetch(lambda r:httpx.Response(304))

    async def test_cached_content_still_requires_public_host_and_robots_permission(self):
        source_cache.store(URL,BODY,'text/html',{'etag':'v1'})
        policy=RobotFileParser();policy.parse(['User-agent: *','Disallow: /investors'])
        with self.assertRaisesRegex(ValueError,'robots.txt'):
            await self.fetch(lambda r: self.fail('Blocked request reached network'),policy=policy)
        with patch.object(documents,'public_host',new=AsyncMock(side_effect=ValueError('Private address'))):
            with self.assertRaisesRegex(ValueError,'Private address'):
                await documents.Fetcher(['example.com']).raw(URL)

    async def test_smaller_download_limit_does_not_trust_larger_cache(self):
        source_cache.store(URL,BODY,'text/html',{'etag':'v1'})
        def response(request):
            self.assertNotIn('if-none-match',request.headers)
            return httpx.Response(200,content=BODY)
        with self.assertRaisesRegex(ValueError,'download size limit'):
            await self.fetch(response,limit=10)

    def test_parser_cache_reuses_original_text_and_recovers_from_corruption(self):
        original=documents.HTMLText
        with patch.object(documents,'HTMLText',wraps=original) as parser:
            first=documents.extract_cached(BODY,'text/html')
            second=documents.extract_cached(BODY,'text/html')
            self.assertEqual(first,second)
            self.assertEqual(parser.call_count,1)
            target=next((source_cache.root()/'parsed').glob('*.json'))
            envelope=json.loads(target.read_text())
            envelope['payload']['pages']=['Invented cached text that must never be accepted. '*3]
            target.write_text(json.dumps(envelope))
            self.assertEqual(documents.extract_cached(BODY,'text/html'),first)
            self.assertEqual(parser.call_count,2)
            documents.extract_cached(BODY+b'Changed body.','text/html')
            self.assertEqual(parser.call_count,3)

    def test_invalid_validator_cannot_inject_request_headers(self):
        self.assertEqual(source_cache.validators({'etag':'valid\r\nAuthorization: secret'}),{})
