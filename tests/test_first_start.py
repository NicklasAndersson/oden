"""No setup wizard: first start, Signal connect from the Signal tab, the Obsidian tab."""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

import oden.config as cfg
from oden.config_db import get_all_config, init_db, save_all_config
from oden.web_server import create_app


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "oden-home"
        # bootstrap() moves the module's paths; put them back afterwards.
        saved = (cfg.ODEN_HOME, cfg.CONFIG_DB, cfg.SIGNAL_DATA_PATH)
        self.addCleanup(lambda: cfg._update_paths(saved[0]))
        patches = [
            unittest.mock.patch("oden.config.get_oden_home_path", return_value=None),
            unittest.mock.patch("oden.config.DEFAULT_ODEN_HOME", self.home),
            unittest.mock.patch("oden.config.set_oden_home_path", return_value=True),
            unittest.mock.patch("oden.config.validate_path_within_home", side_effect=lambda p, **_: (p, None)),
            unittest.mock.patch("oden.config.DEFAULT_VAULT_PATH", Path(self.tmp.name) / "vault"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_first_start_creates_defaults_with_signal_off(self):
        self.assertTrue(cfg.bootstrap())
        stored = get_all_config(self.home / "config.db")
        self.assertFalse(stored["signal_enabled"])
        self.assertTrue((self.home / "signal-data").is_dir())

    def test_oden_vault_sets_the_first_start_vault(self):
        with unittest.mock.patch.dict("os.environ", {"ODEN_VAULT": "/vault"}):
            cfg.bootstrap()
        self.assertEqual(get_all_config(self.home / "config.db")["vault_path"], "/vault")

    def test_existing_database_is_kept(self):
        self.home.mkdir()
        db = self.home / "config.db"
        init_db(db)
        save_all_config(db, {"signal_enabled": True, "signal_number": "+46701234567", "vault_path": "/v"})

        self.assertFalse(cfg.bootstrap())
        stored = get_all_config(db)
        self.assertEqual(stored["signal_number"], "+46701234567")
        self.assertTrue(stored["signal_enabled"])

    def test_corrupt_database_is_reported_not_replaced(self):
        self.home.mkdir()
        (self.home / "config.db").write_bytes(b"not a database")
        with (
            unittest.mock.patch("oden.config.setup_oden_home", return_value=(True, None)),
            unittest.mock.patch("oden.config.CONFIG_DB", self.home / "config.db"),
            self.assertRaisesRegex(RuntimeError, "Flytta undan"),
        ):
            cfg.bootstrap()
        self.assertEqual((self.home / "config.db").read_bytes(), b"not a database")


class SignalConfigProblemTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "config.db"
        init_db(self.db)
        p = unittest.mock.patch("oden.config.CONFIG_DB", self.db)
        p.start()
        self.addCleanup(p.stop)

    def test_placeholder_number(self):
        save_all_config(self.db, {"signal_number": "+46XXXXXXXXX"})
        self.assertIn("Inget Signal-konto", cfg.signal_config_problem())

    def test_account_missing_from_signal_cli(self):
        save_all_config(self.db, {"signal_number": "+46701234567"})
        with unittest.mock.patch(
            "oden.config.validate_signal_number", return_value=(False, "invalid_account", [{"number": "+46709999999"}])
        ):
            self.assertIn("+46709999999", cfg.signal_config_problem())

    def test_ok(self):
        save_all_config(self.db, {"signal_number": "+46701234567"})
        with unittest.mock.patch("oden.config.validate_signal_number", return_value=(True, None, [])):
            self.assertIsNone(cfg.signal_config_problem())


class SignalConnectApiTest(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "config.db"
        init_db(self.db)
        save_all_config(self.db, {"signal_enabled": False, "signal_number": "+46XXXXXXXXX"})
        self._patches = [
            unittest.mock.patch("oden.web_handlers.signal_connect_handlers.cfg.CONFIG_DB", self.db),
            unittest.mock.patch("oden.config.SIGNAL_ENABLED", False),
            unittest.mock.patch("oden.signal_manager.get_existing_accounts", return_value=[{"number": "+46701234567"}]),
        ]
        for p in self._patches:
            p.start()
        await super().asyncSetUp()

    async def asyncTearDown(self):
        await super().asyncTearDown()
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    async def test_status_lists_existing_accounts(self):
        data = await (await self.client.get("/api/signal/connect/status?accounts=1")).json()
        self.assertFalse(data["signal_enabled"])
        self.assertEqual(data["accounts"], [{"number": "+46701234567"}])

    async def test_use_existing_account_turns_signal_on(self):
        resp = await self.client.post("/api/signal/connect/use", json={"signal_number": "+46701234567"})
        self.assertEqual(resp.status, 200)
        self.assertTrue((await resp.json())["restart_required"])
        stored = get_all_config(self.db)
        self.assertEqual(stored["signal_number"], "+46701234567")
        self.assertTrue(stored["signal_enabled"])

    async def test_unknown_account_is_rejected(self):
        resp = await self.client.post("/api/signal/connect/use", json={"signal_number": "+46700000000"})
        self.assertEqual(resp.status, 400)
        self.assertIn("+46701234567", (await resp.json())["error"])
        self.assertFalse(get_all_config(self.db)["signal_enabled"])

    async def test_disable(self):
        save_all_config(self.db, {"signal_enabled": True})
        resp = await self.client.post("/api/signal/connect/disable")
        self.assertEqual(resp.status, 200)
        self.assertFalse(get_all_config(self.db)["signal_enabled"])

    async def test_linking_refused_while_signal_runs(self):
        with unittest.mock.patch("oden.web_handlers.signal_connect_handlers._daemon_running", return_value=True):
            resp = await self.client.post("/api/signal/connect/link")
        self.assertEqual(resp.status, 409)

    async def test_register_needs_international_number(self):
        resp = await self.client.post("/api/signal/connect/register", json={"phone_number": "0701234567"})
        self.assertEqual(resp.status, 400)

    async def test_setup_wizard_is_gone(self):
        self.assertEqual((await self.client.get("/setup")).status, 404)
        self.assertEqual((await self.client.get("/api/setup/status")).status, 404)


class ObsidianApiTest(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_install_template_into_vault_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            template = Path(tmp) / "tpl" / ".obsidian"
            template.mkdir(parents=True)
            (template / "app.json").write_text("{}")
            with (
                unittest.mock.patch("oden.web_handlers.obsidian_handlers.cfg.VAULT_PATH", str(vault)),
                unittest.mock.patch("oden.web_handlers.obsidian_handlers._template_dir", return_value=template),
            ):
                status = await (await self.client.get("/api/obsidian/status")).json()
                first = await (await self.client.post("/api/obsidian/install-template")).json()
                (vault / ".obsidian" / "app.json").write_text('{"mine": true}')
                second = await (await self.client.post("/api/obsidian/install-template")).json()

            self.assertFalse(status["obsidian_installed"])
            self.assertTrue(first["success"])
            self.assertTrue(second["skipped"])
            self.assertEqual((vault / ".obsidian" / "app.json").read_text(), '{"mine": true}')

    async def test_dashboard_has_obsidian_tab_with_vault_fields(self):
        text = await (await self.client.get("/")).text()
        self.assertIn('id="tab-obsidian"', text)
        self.assertIn('id="config-form-obsidian"', text)
        self.assertIn('id="cfg-vault-path"', text)


class ChangeOdenHomeTest(unittest.TestCase):
    """Advanced → Oden-hemkatalog: copy to an empty directory, or switch to one with a config.db."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.old = root / "old"
        (self.old / "signal-data" / "data").mkdir(parents=True)
        (self.old / "signal-data" / "data" / "accounts.json").write_text('{"accounts": []}')
        init_db(self.old / "config.db")
        save_all_config(self.old / "config.db", {"vault_path": "/v", "signal_number": "+46701234567"})
        self.new = root / "new"
        self.pointer: list[Path] = []
        patches = [
            unittest.mock.patch("oden.config.ODEN_HOME", self.old),
            unittest.mock.patch("oden.config.CONFIG_DB", self.old / "config.db"),
            unittest.mock.patch("oden.config.validate_path_within_home", side_effect=lambda p, **_: (Path(p), None)),
            unittest.mock.patch("oden.config.set_oden_home_path", side_effect=lambda p: self.pointer.append(p) or True),
            unittest.mock.patch.dict("os.environ", {}, clear=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        import os

        os.environ.pop("ODEN_HOME", None)

    def test_copy_to_empty_directory(self):
        action, message = cfg.change_oden_home(str(self.new))
        self.assertEqual(action, "copy")
        self.assertEqual(get_all_config(self.new / "config.db")["signal_number"], "+46701234567")
        self.assertTrue((self.new / "signal-data" / "data" / "accounts.json").is_file())
        self.assertTrue((self.old / "config.db").is_file(), "the old home stays as a fallback")
        self.assertEqual(self.pointer, [self.new])
        self.assertIn("efter omstart", message)

    def test_switch_to_existing_home(self):
        self.new.mkdir()
        init_db(self.new / "config.db")
        save_all_config(self.new / "config.db", {"signal_number": "+46709999999"})
        action, _ = cfg.change_oden_home(str(self.new))
        self.assertEqual(action, "switch")
        self.assertEqual(get_all_config(self.new / "config.db")["signal_number"], "+46709999999")

    def test_refuses_non_empty_directory_without_config(self):
        self.new.mkdir()
        (self.new / "something.txt").write_text("x")
        with self.assertRaisesRegex(ValueError, "inte tom"):
            cfg.change_oden_home(str(self.new))
        self.assertEqual(self.pointer, [])

    def test_refuses_nested_and_same(self):
        for path in (self.old, self.old / "sub"):
            with self.assertRaises(ValueError):
                cfg.change_oden_home(str(path))

    def test_locked_by_oden_home_env(self):
        with (
            unittest.mock.patch.dict("os.environ", {"ODEN_HOME": "/data"}),
            self.assertRaisesRegex(ValueError, "ODEN_HOME"),
        ):
            cfg.change_oden_home(str(self.new))


class OdenHomeApiTest(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_get_and_error(self):
        with unittest.mock.patch("oden.config.oden_home_locked_by_env", return_value=True):
            data = await (await self.client.get("/api/oden-home")).json()
            resp = await self.client.post("/api/oden-home", json={"path": "/x"})
        self.assertTrue(data["locked_by_env"])
        self.assertIn("current", data)
        self.assertEqual(resp.status, 400)
        self.assertIn("ODEN_HOME", (await resp.json())["error"])

    async def test_advanced_tab_has_home_section(self):
        text = await (await self.client.get("/")).text()
        self.assertIn('id="oden-home-path"', text)
        self.assertIn("function changeOdenHome", text)
