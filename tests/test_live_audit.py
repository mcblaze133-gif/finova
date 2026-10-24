"""Audit-client recovery must never create duplicate model-consuming jobs."""
import unittest
from unittest.mock import Mock, patch
import httpx
from tools.verify_fresh_company_reports import poll


class AuditPollingTests(unittest.TestCase):
    def test_disconnected_status_read_recovers_without_posting_a_job(self):
        client = Mock()
        response = httpx.Response(200, json={'status':'running'}, request=httpx.Request('GET','http://localhost/status'))
        client.get.side_effect = [httpx.RemoteProtocolError('disconnected'), response]
        with patch('tools.verify_fresh_company_reports.time.sleep'):
            self.assertEqual(poll(client, '/status'), {'status':'running'})
        client.post.assert_not_called()
        self.assertEqual(client.get.call_count, 2)

    def test_persistent_connection_failure_remains_a_failure(self):
        client = Mock()
        client.get.side_effect = httpx.ConnectError('unavailable')
        with patch('tools.verify_fresh_company_reports.time.sleep'):
            with self.assertRaises(httpx.ConnectError):
                poll(client, '/status')
        client.post.assert_not_called()
        self.assertEqual(client.get.call_count, 4)

    def test_wrong_report_is_not_recovered_by_selecting_another_report(self):
        client = Mock()
        client.get.return_value = httpx.Response(404, request=httpx.Request('GET','http://localhost/missing'))
        with self.assertRaises(httpx.HTTPStatusError):
            poll(client, '/missing')
        client.post.assert_not_called()
        self.assertEqual(client.get.call_count, 1)
