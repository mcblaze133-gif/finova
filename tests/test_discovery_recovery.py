"""Bound repeated waits on the same unavailable public discovery service."""
import unittest
from unittest.mock import AsyncMock, Mock, patch
import httpx
from backend import investigation as inv


class DiscoveryRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_backoff_records_gap_then_retries_after_expiry(self):
        clock = Mock()
        clock.monotonic.return_value = 1000
        fetcher = Mock()
        fetcher.fetch = AsyncMock(side_effect=[
            httpx.ConnectTimeout('connection unavailable'),
            (b'{"articles": []}', 'application/json', 'https://api.gdeltproject.org/'),
        ])
        with patch.object(inv, 'time', clock), patch.object(inv, 'SEARCH_NEXT', 0), \
             patch.object(inv, 'SEARCH_BLOCKED_UNTIL', 0), \
             patch.object(inv.documents, 'Fetcher', return_value=fetcher):
            with self.assertRaisesRegex(ValueError, 'coverage incomplete'):
                await inv.public_search('cash flows margins', 'Example Limited')
            with self.assertRaisesRegex(ValueError, 'coverage incomplete'):
                await inv.public_search('competitive market share', 'Example Limited')
            self.assertEqual(fetcher.fetch.await_count, 1)
            clock.monotonic.return_value = 1061
            self.assertEqual(await inv.public_search('cash flows margins', 'Example Limited'), [])
            self.assertEqual(fetcher.fetch.await_count, 2)

    async def test_cooldown_never_substitutes_old_articles(self):
        clock = Mock()
        clock.monotonic.return_value = 1000
        fetcher = Mock()
        fetcher.fetch = AsyncMock()
        with patch.object(inv, 'time', clock), patch.object(inv, 'SEARCH_BLOCKED_UNTIL', 1060), \
             patch.object(inv.documents, 'Fetcher', return_value=fetcher):
            with self.assertRaisesRegex(ValueError, 'coverage incomplete'):
                await inv.public_search('working capital', 'Example Limited')
            fetcher.fetch.assert_not_called()
