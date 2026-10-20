"""Offline foundation checks: no real model calls or production database writes."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from backend import main, storage


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, path, response=None, config=None, failure=None):
        # Keep the ASGI transport real while replacing only Gemini's HTTP client.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            remote = AsyncMock()
            remote.__aenter__.return_value = remote
            remote.post.return_value = response
            remote.post.side_effect = failure
            effective_config = {'GEMINI_FREE_TIER_CONFIRMED': 'true', **(config or {})}
            with patch.object(main, 'reserve_probe'), patch.object(main, "dotenv_values", return_value=effective_config), patch.object(
                main.httpx, "AsyncClient", return_value=remote
            ):
                result = await client.post(path)
            return result, remote

    async def test_health(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    async def test_missing_key_makes_no_request(self):
        response, remote = await self.request("/model/test")
        self.assertEqual(response.status_code, 503)
        remote.post.assert_not_called()

    async def test_unconfirmed_billing_makes_no_request(self):
        response, remote = await self.request('/model/test', config={
            'GEMINI_API_KEY': 'test-only-secret', 'GEMINI_FREE_TIER_CONFIRMED': 'false'})
        self.assertEqual(response.status_code, 503)
        remote.post.assert_not_called()

    async def test_success_ignores_thought_parts(self):
        upstream = httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": "private reasoning", "thought": True}, {"text": "SIGNALAI_OK"}
        ]}}]})
        response, remote = await self.request(
            "/model/test", upstream, {"GEMINI_API_KEY": "test-only-secret"}
        )
        self.assertTrue(response.json()["passed"])
        self.assertNotIn("test-only-secret", response.text)
        remote.post.assert_awaited_once()

    async def test_upstream_errors_are_sanitized_and_not_retried(self):
        for status in (400, 403, 429, 500):
            response, remote = await self.request(
                "/model/test", httpx.Response(status, text="sensitive upstream detail"),
                {"GEMINI_API_KEY": "test-only-secret"}
            )
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("sensitive", response.text)
            remote.post.assert_awaited_once()

    async def test_malformed_upstream_responses(self):
        for body in ([], None, {}, {"candidates": []},
                     {"candidates": [None]}, {"candidates": {}},
                     {"candidates": [{"content": {"parts": [None]}}]},
                     {"candidates": [{"content": {"parts": []}}]},
                     {"candidates": [{"content": {"parts": [{"text": 123}]}}]},
                     {"candidates": [{"content": {"parts": [{"text": " "}]}}]},
                     {"candidates": [{"content": {"parts": [{"text": "hidden", "thought": True}]}}]},
                     {"candidates": [{"content": {"parts": [{"text": "SIGNALAI_OK", "thought": "false"}]}}]}):
            response, _ = await self.request(
                "/model/test", httpx.Response(200, json=body),
                {"GEMINI_API_KEY": "test-only-secret"}
            )
            self.assertEqual(response.status_code, 502)

    async def test_timeout_is_sanitized(self):
        response, remote = await self.request(
            "/model/test", config={"GEMINI_API_KEY": "test-only-secret"},
            failure=httpx.ReadTimeout("sensitive request detail")
        )
        self.assertEqual(response.status_code, 504)
        self.assertNotIn("sensitive", response.text)
        remote.post.assert_awaited_once()

    async def test_startup_initializes_database(self):
        with patch.object(main, "initialize") as initialize, patch.object(main.storage, 'database'):
            async with main.lifespan(main.app):
                initialize.assert_called_once()


class StorageTests(unittest.TestCase):
    def test_schema_is_idempotent_and_foreign_keys_enforced(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(storage, "DB_PATH", Path(folder) / "test.sqlite"):
                connection = storage.connect()
                try:
                    connection.executescript(storage.SCHEMA)
                    connection.executescript(storage.SCHEMA)
                    self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(
                            "INSERT INTO passages(document_id,pdf_page,text) VALUES (999,1,'orphan')"
                        )
                finally:
                    connection.close()


if __name__ == "__main__":
    unittest.main()
