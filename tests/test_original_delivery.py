import hashlib
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from backend import api,storage
from test_backend_audit import AuditFixture


class OriginalDeliveryTests(AuditFixture,unittest.TestCase):
    def source(self,content):
        path=self.root/'data/raw/source.bin';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        with storage.database() as db:
            db.execute("INSERT INTO documents(id,company,title,original_url,retrieved_at,sha256,local_path) VALUES(1,'hul','Fixture','https://example.test/source',?,?,?)",(storage.now(),hashlib.sha256(content).hexdigest(),'data/raw/source.bin'))
        return path

    def response(self):
        with patch.object(storage,'DATA_DIR',self.root/'data'):return api.original(1)

    def test_pdf_is_inline_with_no_store_and_correct_mime(self):
        self.source(b'%PDF-1.7 fixture')
        response=self.response()
        self.assertEqual(response.media_type,'application/pdf')
        self.assertTrue(response.headers['content-disposition'].startswith('inline'))
        self.assertEqual(response.headers['cache-control'],'no-store')

    def test_html_stays_download_only(self):
        self.source(b'<html><script>untrusted()</script></html>')
        response=self.response()
        self.assertEqual(response.media_type,'application/octet-stream')
        self.assertTrue(response.headers['content-disposition'].startswith('attachment'))
        self.assertEqual(response.headers['x-content-type-options'],'nosniff')

    def test_tampered_original_is_not_served(self):
        path=self.source(b'%PDF-1.7 fixture');path.write_bytes(b'%PDF-1.7 changed')
        with self.assertRaises(HTTPException) as caught:self.response()
        self.assertEqual(caught.exception.status_code,409)
