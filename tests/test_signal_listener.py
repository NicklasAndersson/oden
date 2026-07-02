"""Tests for periodic groups/contacts refresh in signal_listener.py."""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from oden.app_state import AppState
from oden.config_db import init_db
from oden.contacts_db import get_all_contacts, upsert_contacts_bulk
from oden.signal_listener import _periodic_groups_contacts_refresh, log_contacts


class TestLogContacts(unittest.IsolatedAsyncioTestCase):
    """log_contacts() must persist to DB on success and fall back to it on failure."""

    def setUp(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            self.db_path = Path(tmp.name)
        self.db_path.unlink(missing_ok=True)
        init_db(self.db_path)
        self.app_state = AppState()

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    # oden.signal_listener imports `cfg` locally (`from oden import config as cfg`)
    # inside each function, so patches must target oden.config's attributes directly.
    @unittest.mock.patch("oden.signal_listener.get_app_state")
    @unittest.mock.patch("oden.config.SIGNAL_NUMBER", "+460000")
    async def test_persists_contacts_on_successful_rpc(self, mock_get_app_state):
        with unittest.mock.patch("oden.config.CONFIG_DB", self.db_path):
            self.app_state.send_jsonrpc = unittest.mock.AsyncMock(
                return_value={"result": [{"number": "+461", "name": "Alice"}]}
            )
            mock_get_app_state.return_value = self.app_state

            await log_contacts()

        self.assertEqual(self.app_state.contacts["+461"]["name"], "Alice")
        stored = get_all_contacts(self.db_path, account="+460000")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["number"], "+461")

    @unittest.mock.patch("oden.signal_listener.get_app_state")
    @unittest.mock.patch("oden.config.SIGNAL_NUMBER", "+460000")
    async def test_falls_back_to_database_when_rpc_fails(self, mock_get_app_state):
        upsert_contacts_bulk(self.db_path, [{"number": "+462", "name": "Cached Bob"}], account="+460000")

        with unittest.mock.patch("oden.config.CONFIG_DB", self.db_path):
            self.app_state.send_jsonrpc = unittest.mock.AsyncMock(side_effect=Exception("connection lost"))
            mock_get_app_state.return_value = self.app_state

            await log_contacts()

        self.assertEqual(self.app_state.contacts["+462"]["name"], "Cached Bob")


class TestPeriodicRefresh(unittest.IsolatedAsyncioTestCase):
    """The background refresh loop must call log_groups + log_contacts each tick."""

    @unittest.mock.patch("oden.signal_listener.log_contacts", new_callable=unittest.mock.AsyncMock)
    @unittest.mock.patch("oden.signal_listener.log_groups", new_callable=unittest.mock.AsyncMock)
    @unittest.mock.patch("oden.signal_listener.asyncio.sleep", new_callable=unittest.mock.AsyncMock)
    async def test_refreshes_groups_and_contacts_each_tick(self, mock_sleep, mock_log_groups, mock_log_contacts):
        # Run exactly two iterations, then break out via a sentinel exception.
        mock_sleep.side_effect = [None, RuntimeError("stop loop")]

        with self.assertRaises(RuntimeError):
            await _periodic_groups_contacts_refresh(writer=unittest.mock.Mock())

        self.assertEqual(mock_log_groups.await_count, 1)
        self.assertEqual(mock_log_contacts.await_count, 1)

    @unittest.mock.patch("oden.signal_listener.log_contacts", new_callable=unittest.mock.AsyncMock)
    @unittest.mock.patch(
        "oden.signal_listener.log_groups", new_callable=unittest.mock.AsyncMock, side_effect=Exception("boom")
    )
    @unittest.mock.patch("oden.signal_listener.asyncio.sleep", new_callable=unittest.mock.AsyncMock)
    async def test_a_failed_refresh_does_not_kill_the_loop(self, mock_sleep, mock_log_groups, mock_log_contacts):
        mock_sleep.side_effect = [None, RuntimeError("stop loop")]

        with self.assertRaises(RuntimeError):
            await _periodic_groups_contacts_refresh(writer=unittest.mock.Mock())

        # Loop must have survived the exception and reached the second sleep.
        self.assertEqual(mock_sleep.await_count, 2)


if __name__ == "__main__":
    unittest.main()
