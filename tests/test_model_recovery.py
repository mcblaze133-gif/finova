"""Provider transport recovery is bounded, charged to the cap and sanitized."""
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from pydantic import BaseModel
from backend import model


class Reply(BaseModel):
    text: str


class ModelRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, replies):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.side_effect = replies
        with patch.object(model, 'model_settings', return_value=('fixture-key', 'fixture-model')), \
             patch.object(model, 'reserve_call') as reserve, \
             patch.object(model.storage, 'event') as event, \
             patch.object(model.httpx, 'AsyncClient', return_value=client), \
             patch.object(model.asyncio, 'sleep', new=AsyncMock()):
            try:
                result = await model.generate('fixture-run','reviewer',{'company':'fixture'},Reply)
            except model.ModelUnavailable as exc:
                result = exc
        return result, client, reserve, event

    async def test_read_timeout_can_recover_once_with_both_attempts_reserved(self):
        success = httpx.Response(200, json={'candidates':[{'content':{'parts':[{'text':'{"text":"accepted"}'}]}}]})
        result, client, reserve, event = await self.invoke([httpx.ReadTimeout('private upstream detail'), success])
        self.assertEqual(result.text, 'accepted')
        self.assertEqual(client.post.await_count, 2)
        self.assertEqual(reserve.call_count, 2)
        self.assertNotIn('private upstream detail', str(event.call_args_list))

    async def test_persistent_transport_failure_stops_after_two_attempts(self):
        result, client, reserve, event = await self.invoke([httpx.ConnectError('private detail')]*2)
        self.assertIsInstance(result, model.ModelUnavailable)
        self.assertEqual(client.post.await_count, 2)
        self.assertEqual(reserve.call_count, 2)
        self.assertNotIn('private detail', str(result))

    async def test_authentication_and_quota_failures_are_never_retried(self):
        for status in (401,403,429):
            result, client, reserve, event = await self.invoke([httpx.Response(status)])
            self.assertIsInstance(result, model.ModelUnavailable)
            self.assertEqual(result.provider_status, status)
            self.assertEqual(client.post.await_count, 1)
            self.assertEqual(reserve.call_count, 1)
