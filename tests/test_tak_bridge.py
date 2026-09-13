import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from oden.tak.bridge import _DEFAULTS, TakBridge
from oden.tak.pref_package import PackageConfig


class BuildConfigTest(unittest.TestCase):
    def _config(self, settings, env=None):
        with patch.dict("os.environ", env or {}, clear=False):
            return TakBridge({**_DEFAULTS, **settings})._build_config()

    def test_maps_cert_paths_and_url(self):
        cfg = self._config(
            {"cot_url": "tls://tak.example:8089", "tls_client_cert": "/c/oden.p12", "tls_ca_cert": "/c/ca.pem"}
        )
        self.assertEqual(cfg["COT_URL"], "tls://tak.example:8089")
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_CERT"], "/c/oden.p12")
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_CAFILE"], "/c/ca.pem")

    def test_password_comes_from_the_named_env_var(self):
        cfg = self._config(
            {"cot_url": "tls://x:8089", "tls_client_password_env": "MY_TAK_PW"},
            env={"MY_TAK_PW": "s3cret"},
        )
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_PASSWORD"], "s3cret")

    def test_verify_off_sets_dont_verify(self):
        cfg = self._config({"cot_url": "tls://x:8089", "tls_verify": False})
        self.assertEqual(cfg["PYTAK_TLS_DONT_VERIFY"], "1")
        cfg_on = self._config({"cot_url": "tls://x:8089", "tls_verify": True})
        self.assertNotIn("PYTAK_TLS_DONT_VERIFY", cfg_on)

    def test_hostname_check_defaults_off(self):
        cfg = self._config({"cot_url": "tls://x:8089"})
        self.assertEqual(cfg["PYTAK_TLS_DONT_CHECK_HOSTNAME"], "1")
        cfg_on = self._config({"cot_url": "tls://x:8089", "tls_check_hostname": True})
        self.assertNotIn("PYTAK_TLS_DONT_CHECK_HOSTNAME", cfg_on)

    def test_pref_package_fills_url_and_certs(self):
        package = PackageConfig(
            cot_url="ssl://tak.example:8089",
            client_cert="/tmp/c.p12",
            client_password="pw",
            ca_pem="/tmp/ca.pem",
        )
        with patch("oden.tak.bridge.package_settings", return_value=package):
            cfg = self._config({"pref_package": "/tmp/pkg.zip"})
        self.assertEqual(cfg["COT_URL"], "ssl://tak.example:8089")
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_CERT"], "/tmp/c.p12")
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_PASSWORD"], "pw")
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_CAFILE"], "/tmp/ca.pem")

    def test_trust_only_package_without_credentials_is_a_readable_error(self):
        """Regression: this used to surface as a TypeError from inside pytak."""
        package = PackageConfig(cot_url="ssl://tak.example:8089", ca_pem="/tmp/ca.pem", needs_enrollment=True)
        with (
            patch("oden.tak.bridge.package_settings", return_value=package),
            self.assertRaises(ValueError) as ctx,
        ):
            self._config({"pref_package": "/tmp/pkg.zip"})
        self.assertIn("enrollment", str(ctx.exception))

    def test_password_containing_a_percent_sign_survives(self):
        """ConfigParser's BasicInterpolation reads % as syntax and rejects the value."""
        cfg = self._config(
            {
                "cot_url": "tls://x:8089",
                "enroll_username": "25HVBAT675",
                "enroll_password_env": "ENR_PW",
                "tls_client_password_env": "CERT_PW",
            },
            env={"ENR_PW": "Kx4MGg%sj56Y#P?", "CERT_PW": "100%%safe"},
        )
        self.assertEqual(cfg["PYTAK_TLS_CERT_ENROLLMENT_PASSWORD"], "Kx4MGg%sj56Y#P?")
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_PASSWORD"], "100%%safe")

    def test_enrollment_username_and_env_password(self):
        cfg = self._config(
            {"cot_url": "tls://x:8089", "enroll_username": "nicklas", "enroll_password_env": "ENR_PW"},
            env={"ENR_PW": "pw"},
        )
        self.assertEqual(cfg["PYTAK_TLS_CERT_ENROLLMENT_USERNAME"], "nicklas")
        self.assertEqual(cfg["PYTAK_TLS_CERT_ENROLLMENT_PASSWORD"], "pw")

    def test_no_enrollment_keys_without_username(self):
        cfg = self._config({"cot_url": "tls://x:8089"})
        self.assertNotIn("PYTAK_TLS_CERT_ENROLLMENT_USERNAME", cfg)


class PublishTest(unittest.IsolatedAsyncioTestCase):
    async def test_publish_enqueues_and_counts(self):
        bridge = TakBridge(dict(_DEFAULTS))
        queue: asyncio.Queue = asyncio.Queue()
        bridge._tx_queue = queue
        bridge._run_task = asyncio.create_task(asyncio.sleep(3600))
        self.addCleanup(bridge._run_task.cancel)

        self.assertTrue(await bridge.publish(b"<event/>"))
        self.assertEqual(queue.get_nowait(), b"<event/>")
        self.assertEqual(bridge.sent_count, 1)
        self.assertIsNotNone(bridge.last_tx_at)

    async def test_publish_noop_when_not_running(self):
        bridge = TakBridge(dict(_DEFAULTS))
        self.assertFalse(await bridge.publish(b"<event/>"))
        self.assertEqual(bridge.sent_count, 0)

    async def test_publish_drops_on_full_queue(self):
        bridge = TakBridge(dict(_DEFAULTS))
        bridge._tx_queue = asyncio.Queue(maxsize=1)
        bridge._tx_queue.put_nowait(b"first")
        bridge._run_task = asyncio.create_task(asyncio.sleep(3600))
        self.addCleanup(bridge._run_task.cancel)

        self.assertFalse(await bridge.publish(b"second"))
        self.assertEqual(bridge.sent_count, 0)


class _FakeCLITool:
    """Connects fine; the first run() dies like a dropped socket, the second stays up."""

    instances: list = []
    runs = 0

    def __init__(self, config, tx_queue=None, rx_queue=None):
        self.tx_queue = tx_queue or asyncio.Queue()
        self.rx_queue = rx_queue or asyncio.Queue()
        _FakeCLITool.instances.append(self)

    async def setup(self):
        pass

    async def run(self):
        _FakeCLITool.runs += 1
        if _FakeCLITool.runs == 1:
            raise ConnectionResetError("server went away")
        await asyncio.sleep(3600)


class ReconnectTest(unittest.IsolatedAsyncioTestCase):
    async def test_reconnects_and_keeps_queues(self):
        _FakeCLITool.instances, _FakeCLITool.runs = [], 0
        bridge = TakBridge({**_DEFAULTS, "cot_url": "tcp://x:8087"})
        with (
            patch.dict("sys.modules", {"pytak": SimpleNamespace(CLITool=_FakeCLITool)}),
            patch("oden.tak.bridge._RECONNECT_MIN", 0.0),
            patch("oden.tak.listener.start_tak_listener", return_value=None),
        ):
            await bridge.start()
            self.addCleanup(bridge.stop)
            first_tx, first_rx = bridge._tx_queue, bridge.rx_queue
            for _ in range(20):  # let run() fail, backoff (0 s) and reconnect
                await asyncio.sleep(0)

        self.assertEqual(_FakeCLITool.runs, 2)
        self.assertEqual(len(_FakeCLITool.instances), 2)
        self.assertTrue(bridge.connected)
        self.assertTrue(bridge.is_running)
        self.assertIs(bridge._tx_queue, first_tx)
        self.assertIs(bridge.rx_queue, first_rx)
        self.assertIs(_FakeCLITool.instances[1].rx_queue, first_rx)


class SafeErrorTest(unittest.TestCase):
    """Errors reach the log, last_error and the TAK tab — they must not carry secrets."""

    def _settings(self, **overrides):
        return {**_DEFAULTS, "enroll_password": "Kx4MGg%sj56Y#P?", **overrides}

    def test_a_password_quoted_by_a_library_is_scrubbed(self):
        from oden.tak.bridge import safe_error

        # ConfigParser really does put the rejected value in its message.
        exc = ValueError("invalid interpolation syntax in 'Kx4MGg%sj56Y#P?' at position 6")
        text = safe_error(exc, self._settings())

        self.assertNotIn("Kx4MGg", text)
        self.assertIn("***", text)

    def test_a_password_held_in_an_env_var_is_scrubbed_too(self):
        from oden.tak.bridge import safe_error

        settings = self._settings(enroll_password="", enroll_password_env="ENR_PW")
        with patch.dict("os.environ", {"ENR_PW": "hemlig-fras"}):
            text = safe_error(ValueError("kunde inte använda hemlig-fras"), settings)

        self.assertNotIn("hemlig-fras", text)

    def test_ordinary_errors_pass_through_intact(self):
        from oden.tak.bridge import safe_error

        text = safe_error(ConnectionRefusedError("Connect call failed"), self._settings())
        self.assertIn("Connect call failed", text)

    def test_no_configured_password_is_not_a_wildcard(self):
        from oden.tak.bridge import safe_error

        settings = {**_DEFAULTS, "enroll_password": "", "tls_client_password": ""}
        text = safe_error(ValueError("helt vanligt fel"), settings)
        self.assertIn("helt vanligt fel", text)


class CertExpiryTest(unittest.TestCase):
    def test_none_when_no_cert(self):
        from oden.tak.bridge import cert_expiry

        self.assertIsNone(cert_expiry({}))
        self.assertIsNone(cert_expiry({"tls_client_cert": "/nonexistent/x.p12"}))


if __name__ == "__main__":
    unittest.main()
