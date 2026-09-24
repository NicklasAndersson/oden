import asyncio
import contextlib
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

    def test_password_containing_a_percent_sign_reaches_pytak_intact(self):
        """A "%" has to survive two ConfigParsers: ours, then pytak's own.

        Ours is built with interpolation off, so it would reject the value on
        assignment. pytak's get_tls_config() then copies the TLS keys into a
        second ConfigParser that *does* interpolate, so the value has to arrive
        there doubled. This asserts the end result against the real pytak — if
        pytak ever stops interpolating, this fails rather than quietly handing
        the server a password full of "%%".
        """
        import pytak.client_functions as client_functions

        cfg = self._config(
            {"cot_url": "tls://x:8089", "tls_client_cert": "/c/egen.p12", "tls_client_password_env": "CERT_PW"},
            env={"CERT_PW": "Kx4MGg%sj56Y#P?"},
        )

        tls = client_functions.get_tls_config(cfg)
        self.assertEqual(tls.get("PYTAK_TLS_CLIENT_PASSWORD"), "Kx4MGg%sj56Y#P?")

    def test_cot_url_is_not_escaped(self):
        """COT_URL is read straight off our section, so it must not be doubled."""
        cfg = self._config({"cot_url": "tls://x:8089"})
        self.assertEqual(cfg["COT_URL"], "tls://x:8089")

    def test_enrollment_credentials_never_enter_pytak_config(self):
        """pytak would re-enroll on every connect and leave the .p12 in $TMPDIR; Oden does it instead."""
        bridge = TakBridge(
            {**_DEFAULTS, "cot_url": "tls://x:8089", "enroll_username": "nicklas", "enroll_password_env": "ENR_PW"}
        )
        with patch.dict("os.environ", {"ENR_PW": "pw"}):
            cfg = bridge._build_config()

        self.assertTrue(bridge._needs_enrollment)
        self.assertNotIn("PYTAK_TLS_CERT_ENROLLMENT_USERNAME", cfg)
        self.assertNotIn("PYTAK_TLS_CERT_ENROLLMENT_PASSWORD", cfg)
        self.assertNotIn("PYTAK_TLS_CERT_ENROLLMENT_PASSPHRASE", cfg)

    def test_no_enrollment_without_a_username(self):
        bridge = TakBridge({**_DEFAULTS, "cot_url": "tls://x:8089"})
        bridge._build_config()
        self.assertFalse(bridge._needs_enrollment)


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

    def test_a_fragment_of_a_password_is_scrubbed(self):
        from oden.tak.bridge import safe_error

        # What pytak's interpolation error actually looked like: only the tail.
        exc = ValueError("'%' must be followed by '%' or '(', found: '%sj56Y#P?'")
        text = safe_error(exc, self._settings())

        self.assertNotIn("sj56Y#P?", text)
        self.assertIn("***", text)

    def test_a_short_password_is_not_matched_letter_by_letter(self):
        from oden.tak.bridge import safe_error

        # Too short to mask safely without mangling unrelated text.
        text = safe_error(ValueError("anslutningen bröts"), self._settings(enroll_password="abc"))
        self.assertEqual(text, repr(ValueError("anslutningen bröts")))

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


class _EofReader:
    """A socket reader whose far end has gone away, like pytak's after a drop."""

    def __init__(self, at_eof=True):
        self._at_eof = at_eof
        self.reads = 0

    def at_eof(self):
        return self._at_eof

    async def readuntil(self, separator):
        """What pytak's RXWorker calls; at EOF it returns instantly, forever."""
        self.reads += 1
        raise asyncio.IncompleteReadError(partial=b"", expected=None)


class _RxWorkerStub:
    """Stands in for pytak's RXWorker between setup() and run(): carries the reader."""

    def __init__(self, reader):
        self.reader = reader


class _SpinningCLITool:
    """pytak as it really behaves after a dropped link.

    ``run()`` never returns (RXWorker swallows the EOF error and loops), and the
    worker it started keeps running unless someone cancels it explicitly.
    """

    instances: list = []

    def __init__(self, config, tx_queue=None, rx_queue=None):
        self.tx_queue = tx_queue or asyncio.Queue()
        self.rx_queue = rx_queue or asyncio.Queue()
        self.reader = _EofReader()
        self.tasks = {_RxWorkerStub(self.reader)}  # a set, exactly like pytak's
        self.running_tasks: set = set()
        _SpinningCLITool.instances.append(self)

    async def setup(self):
        pass

    async def _worker(self):
        while True:  # exactly pytak's RXWorker.run loop
            with contextlib.suppress(asyncio.IncompleteReadError):
                # readcot swallows this, which is what makes run() spin forever
                await self.reader.readuntil(b"</event>")
            await asyncio.sleep(0)

    async def run(self):
        self.running_tasks = {asyncio.create_task(self._worker())}
        await asyncio.wait(self.running_tasks, return_when=asyncio.FIRST_EXCEPTION)


class DroppedLinkTest(unittest.IsolatedAsyncioTestCase):
    """A link that dies must be noticed, must not spin, and must not leak."""

    def _bridge(self):
        _SpinningCLITool.instances = []
        return TakBridge({**_DEFAULTS, "cot_url": "tcp://x:8087"})

    async def test_eof_is_detected_and_the_bridge_reconnects(self):
        bridge = self._bridge()
        with (
            patch.dict("sys.modules", {"pytak": SimpleNamespace(CLITool=_SpinningCLITool)}),
            patch("oden.tak.bridge._EOF_POLL", 0.0),
            patch("oden.tak.bridge._RECONNECT_MIN", 0.0),
            patch("oden.tak.listener.start_tak_listener", return_value=None),
        ):
            await bridge.start()
            for _ in range(50):  # the watchdog fires, then a fresh connect
                await asyncio.sleep(0)
            self.assertGreater(len(_SpinningCLITool.instances), 1, "bryggan försökte aldrig återansluta")
            await bridge.stop()  # while pytak is still patched

    async def test_the_dead_worker_does_not_spin_on(self):
        bridge = self._bridge()
        with (
            patch.dict("sys.modules", {"pytak": SimpleNamespace(CLITool=_SpinningCLITool)}),
            patch("oden.tak.bridge._EOF_POLL", 0.0),
            patch("oden.tak.bridge._RECONNECT_MIN", 3600.0),  # one attempt, then park
            patch("oden.tak.listener.start_tak_listener", return_value=None),
        ):
            await bridge.start()
            for _ in range(50):
                await asyncio.sleep(0)
            first = _SpinningCLITool.instances[0]
            settled = first.reader.reads
            # The drop is reported instead of being hidden behind a green light.
            self.assertIn("stängde anslutningen", bridge.last_error or "")
            self.assertFalse(bridge.connected)
            for _ in range(200):  # plenty of loop turns for a spinner to run wild
                await asyncio.sleep(0)
            await bridge.stop()

        self.assertEqual(first.reader.reads, settled, "pytaks worker snurrar vidare efter avbrottet")
        self.assertTrue(all(t.done() for t in first.running_tasks))

    async def test_stop_leaves_no_pytak_tasks_behind(self):
        before = len(asyncio.all_tasks())
        for _ in range(3):  # the TAK tab does stop+start on every save
            bridge = self._bridge()
            with (
                patch.dict("sys.modules", {"pytak": SimpleNamespace(CLITool=_SpinningCLITool)}),
                patch("oden.tak.bridge._EOF_POLL", 3600.0),  # keep the link "up"
                patch("oden.tak.bridge._RECONNECT_MIN", 3600.0),
                patch("oden.tak.listener.start_tak_listener", return_value=None),
            ):
                await bridge.start()
                for _ in range(10):
                    await asyncio.sleep(0)
                await bridge.stop()

        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual(len(asyncio.all_tasks()), before, "en start/stopp-omgång lämnade tasks kvar")
        self.assertIsNone(bridge._clitool)
        for tool in _SpinningCLITool.instances:
            self.assertTrue(all(t.done() for t in tool.running_tasks))


if __name__ == "__main__":
    unittest.main()


def _p12(password: bytes | None) -> bytes:
    """A throwaway client cert + key as PKCS#12, optionally password-protected."""
    import datetime as _dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, NoEncryption, pkcs12
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "oden-test")])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + _dt.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    encryption = BestAvailableEncryption(password) if password else NoEncryption()
    return pkcs12.serialize_key_and_certificates(b"oden", key, cert, None, encryption)


class P12WithoutPasswordTest(unittest.TestCase):
    """A .p12 with no password configured used to reach pytak as str.encode(None)."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        home = patch("oden.config.ODEN_HOME", str(self.dir / "home"))
        home.start()
        self.addCleanup(home.stop)

    def _config(self, blob, env=None):
        import os

        cert = self.dir / "client-cert-oden.p12"
        cert.write_bytes(blob)
        settings = {**_DEFAULTS, "cot_url": "tls://tak.example:8089", "tls_client_cert": str(cert)}
        with patch.dict("os.environ", env or {}, clear=False):
            if not env:  # the password variable must really be unset
                os.environ.pop(_DEFAULTS["tls_client_password_env"], None)
            return TakBridge(settings)._build_config()

    def test_a_p12_without_password_is_handed_to_pytak_as_pem(self):
        import os

        cfg = self._config(_p12(None))
        self.assertTrue(cfg["PYTAK_TLS_CLIENT_CERT"].endswith(".cert.pem"))
        self.assertTrue(cfg["PYTAK_TLS_CLIENT_KEY"].endswith(".key.pem"))
        self.assertNotIn("PYTAK_TLS_CLIENT_PASSWORD", cfg)
        with open(cfg["PYTAK_TLS_CLIENT_KEY"], "rb") as handle:
            self.assertIn(b"PRIVATE KEY", handle.read())
        if os.name == "posix":
            self.assertEqual(os.stat(cfg["PYTAK_TLS_CLIENT_KEY"]).st_mode & 0o777, 0o600)

    def test_a_protected_p12_without_password_says_what_to_set(self):
        with self.assertRaises(ValueError) as caught:
            self._config(_p12(b"atakatak"))
        self.assertIn("lösenordsskyddat", str(caught.exception))
        self.assertIn(_DEFAULTS["tls_client_password_env"], str(caught.exception))

    def test_a_password_typed_in_the_tak_tab_is_used(self):
        import os

        cert = self.dir / "client-cert-oden.p12"
        cert.write_bytes(_p12(b"atakatak"))
        settings = {
            **_DEFAULTS,
            "cot_url": "tls://tak.example:8089",
            "tls_client_cert": str(cert),
            "tls_client_password": "atakatak",
        }
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop(_DEFAULTS["tls_client_password_env"], None)
            cfg = TakBridge(settings)._build_config()
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_PASSWORD"], "atakatak")
        self.assertTrue(cfg["PYTAK_TLS_CLIENT_CERT"].endswith(".p12"))

    def test_the_error_points_to_the_field(self):
        with self.assertRaises(ValueError) as caught:
            self._config(_p12(b"atakatak"))
        self.assertIn("Certlösenord i TAK-fliken", str(caught.exception))

    def test_with_the_password_set_the_p12_goes_to_pytak_unchanged(self):
        cfg = self._config(_p12(b"atakatak"), env={_DEFAULTS["tls_client_password_env"]: "atakatak"})
        self.assertTrue(cfg["PYTAK_TLS_CLIENT_CERT"].endswith(".p12"))
        self.assertEqual(cfg["PYTAK_TLS_CLIENT_PASSWORD"], "atakatak")
