import asyncio
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from oden.tak.bridge import _DEFAULTS, TakBridge

_HAS_PYTAK = importlib.util.find_spec("pytak") is not None


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

    def test_password_comes_from_named_env_var_only(self):
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

    @unittest.skipUnless(_HAS_PYTAK, "pytak not installed (oden[tak])")
    def test_pref_package_fills_url_and_certs(self):
        fake = {
            "COT_URL": "ssl://tak.example:8089",
            "PYTAK_TLS_CLIENT_CERT": "/tmp/c.pem",
            "PYTAK_TLS_CLIENT_KEY": "/tmp/k.pem",
            "PYTAK_TLS_CLIENT_CAFILE": "/tmp/ca.pem",
        }
        with patch("pytak.read_pref_package", return_value=fake):
            cfg = self._config({"pref_package": "/tmp/pkg.zip"})
        self.assertEqual(cfg["COT_URL"], "ssl://tak.example:8089")
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_CAFILE"], "/tmp/ca.pem")

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


class CertExpiryTest(unittest.TestCase):
    def test_none_when_no_cert(self):
        from oden.tak.bridge import cert_expiry

        self.assertIsNone(cert_expiry({}))
        self.assertIsNone(cert_expiry({"tls_client_cert": "/nonexistent/x.p12"}))


if __name__ == "__main__":
    unittest.main()
