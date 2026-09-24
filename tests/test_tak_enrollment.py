"""Oden-owned enrollment: enroll once, cache the cert, hand pytak a plain client cert.

pytak's own enrollment runs on every connect and leaves each .p12 in $TMPDIR.
``CertificateEnrollment`` is faked here so no network is touched; the fake
writes a real PKCS#12 with ``cryptography`` (or nothing, to simulate failure).
"""

import asyncio
import datetime as dt
import logging
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from oden.tak.enrollment import EnrolledCert, cached_cert, enroll, ensure_cert

HOST = "tak.example.mil"
USER = "25HVBAT675"
PASSWORD = "Kx4MGg%sj56Y#P?"


def _ca_cert() -> x509.Certificate:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TAK Test CA")])
    now = dt.datetime.now(dt.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )


def _client_p12(passphrase: str, *, days_valid: int, cas: list | None = None) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, USER)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=days_valid))
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=USER.encode(),
        key=key,
        cert=cert,
        cas=cas,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode()),
    )


# Recorded enrollment arguments, deliberately NOT an attribute of FakeEnrollment: the
# recorded password would taint the class object, and CodeQL then reads the unrelated
# FakeEnrollment.fail_with below as the password being logged in clear text.
_CALLS: list[dict] = []


class FakeEnrollment:
    """Stand-in for pytak.crypto_classes.CertificateEnrollment.

    Mirrors the real thing's contract: writes the .p12 to output_path on success;
    on failure logs the reason to ``pytak.crypto_classes`` and writes nothing.
    Arguments of each call land in the module-level ``_CALLS``.
    """

    fail_with: str | None = None
    days_valid = 365
    with_ca = False

    def __init__(self, trust_store_path=None):
        pass

    async def begin_enrollment(self, *, domain, username, password, output_path, passphrase, **_):
        _CALLS.append({"domain": domain, "username": username, "password": password})
        # Real pytak WARNs this on every attempt, success or failure.
        logging.getLogger("pytak.crypto_classes").warning("SSL verification disabled - NOT for production use!")
        if FakeEnrollment.fail_with:
            logging.getLogger("pytak.crypto_classes").error(FakeEnrollment.fail_with)
            return
        cas = [_ca_cert()] if FakeEnrollment.with_ca else None
        Path(output_path).write_bytes(_client_p12(passphrase, days_valid=FakeEnrollment.days_valid, cas=cas))


def _fake_pytak():
    return patch.dict(
        sys.modules,
        {"pytak": SimpleNamespace(), "pytak.crypto_classes": SimpleNamespace(CertificateEnrollment=FakeEnrollment)},
    )


class EnrollmentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = Path(self._tmp.name) / "tak"
        _CALLS.clear()
        FakeEnrollment.fail_with = None
        FakeEnrollment.days_valid = 365

    async def test_enrolls_once_and_reuses_the_cached_cert(self):
        with _fake_pytak():
            first = await ensure_cert(HOST, USER, PASSWORD, self.dest)
            second = await ensure_cert(HOST, USER, PASSWORD, self.dest)

        self.assertEqual(len(_CALLS), 1)
        self.assertEqual(first, second)
        self.assertTrue(Path(first.path).is_file())
        self.assertTrue(Path(first.path).parent == self.dest)

    async def test_key_material_is_owner_only(self):
        with _fake_pytak():
            cert = await ensure_cert(HOST, USER, PASSWORD, self.dest)

        p12 = Path(cert.path)
        self.assertEqual(p12.stat().st_mode & 0o777, 0o600)
        self.assertEqual(p12.with_suffix(".pass").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.dest.stat().st_mode & 0o777, 0o700)

    async def test_passphrase_is_safe_for_pytaks_config_parser(self):
        with _fake_pytak():
            cert = await ensure_cert(HOST, USER, PASSWORD, self.dest)
        self.assertNotIn("%", cert.passphrase)
        self.assertGreaterEqual(len(cert.passphrase), 16)

    async def test_a_cert_about_to_expire_is_renewed(self):
        FakeEnrollment.days_valid = 3  # inside the 7-day renewal window
        with _fake_pytak():
            await ensure_cert(HOST, USER, PASSWORD, self.dest)
            FakeEnrollment.days_valid = 365
            renewed = await ensure_cert(HOST, USER, PASSWORD, self.dest)

        self.assertEqual(len(_CALLS), 2)
        self.assertGreater(renewed.expires_at, dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=300))

    async def test_a_different_account_gets_its_own_cert(self):
        with _fake_pytak():
            a = await ensure_cert(HOST, USER, PASSWORD, self.dest)
            b = await ensure_cert(HOST, "annan", PASSWORD, self.dest)
        self.assertNotEqual(a.path, b.path)
        self.assertEqual(len(_CALLS), 2)

    async def test_failure_reports_pytaks_reason_in_swedish(self):
        """pytak swallows the exception; its log line is the only evidence, so it goes in the error."""
        FakeEnrollment.fail_with = "Error generating CSR: 401, message='Unauthorized'"
        with _fake_pytak(), self.assertRaises(ValueError) as ctx:
            await enroll(HOST, USER, PASSWORD, self.dest)

        message = str(ctx.exception)
        self.assertIn("enrollment", message)
        self.assertIn(f"{HOST}:8446", message)
        self.assertIn("401", message)
        self.assertIn("användarnamn", message)
        # pytak's per-attempt WARNING is not a cause and must not read like one
        self.assertNotIn("SSL verification disabled", message)
        self.assertFalse(list(self.dest.glob("*.p12")), "no half-written cert may be left behind")

    async def test_failure_message_never_carries_the_password(self):
        FakeEnrollment.fail_with = f"Error generating CSR: auth failed for password {PASSWORD}"
        with _fake_pytak(), self.assertRaises(ValueError) as ctx:
            await enroll(HOST, USER, PASSWORD, self.dest)
        self.assertNotIn(PASSWORD, str(ctx.exception))
        self.assertNotIn("sj56Y#P?", str(ctx.exception))

    async def test_a_stale_cached_file_is_not_mistaken_for_a_fresh_result(self):
        with _fake_pytak():
            await ensure_cert(HOST, USER, PASSWORD, self.dest)
            FakeEnrollment.fail_with = "Error generating CSR: 401"
            with self.assertRaises(ValueError):
                await enroll(HOST, USER, PASSWORD, self.dest)
        self.assertIsNone(cached_cert(HOST, USER, self.dest))

    def test_cached_cert_is_none_when_nothing_is_cached(self):
        self.assertIsNone(cached_cert(HOST, USER, self.dest))

    def test_cached_cert_ignores_a_pair_it_cannot_open(self):
        self.dest.mkdir(parents=True)
        p12, pw = self.dest / "enrolled-x.p12", self.dest / "enrolled-x.pass"
        from oden.tak.enrollment import _cache_paths

        p12, pw = _cache_paths(HOST, USER, self.dest)
        p12.write_bytes(b"inte en p12")
        pw.write_text("fel")
        self.assertIsNone(cached_cert(HOST, USER, self.dest))


class _FakeCLITool:
    instances: list = []

    def __init__(self, config, tx_queue=None, rx_queue=None):
        self.config = config
        self.tx_queue = tx_queue or asyncio.Queue()
        self.rx_queue = rx_queue or asyncio.Queue()
        _FakeCLITool.instances.append(self)

    async def setup(self):
        pass

    async def run(self):
        await asyncio.sleep(3600)


class BridgeEnrollmentTest(unittest.IsolatedAsyncioTestCase):
    """start() must give pytak a client cert, never the credentials."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = Path(self._tmp.name) / "tak"
        _CALLS.clear()
        FakeEnrollment.fail_with = None
        FakeEnrollment.days_valid = 365
        FakeEnrollment.with_ca = False
        _FakeCLITool.instances = []

    async def test_start_points_pytak_at_the_enrolled_cert(self):
        from oden.tak.bridge import _DEFAULTS, TakBridge

        bridge = TakBridge(
            {**_DEFAULTS, "cot_url": f"ssl://{HOST}:8089", "enroll_username": USER, "enroll_password": PASSWORD}
        )
        with (
            patch.dict(
                sys.modules,
                {
                    "pytak": SimpleNamespace(CLITool=_FakeCLITool),
                    "pytak.crypto_classes": SimpleNamespace(CertificateEnrollment=FakeEnrollment),
                },
            ),
            patch("oden.tak.bridge.tak_dir", return_value=self.dest),
            patch("oden.tak.listener.start_tak_listener", return_value=None),
        ):
            await bridge.start()
            self.addCleanup(bridge.stop)

        config = _FakeCLITool.instances[0].config
        self.assertEqual(_CALLS, [{"domain": HOST, "username": USER, "password": PASSWORD}])
        self.assertEqual(config.get("PYTAK_TLS_CLIENT_CERT"), bridge.enrolled.path)
        self.assertEqual(config.get("PYTAK_TLS_CLIENT_PASSWORD"), bridge.enrolled.passphrase)
        self.assertNotIn("PYTAK_TLS_CERT_ENROLLMENT_PASSWORD", config)
        self.assertIsInstance(bridge.enrolled, EnrolledCert)

    async def test_enrollment_failure_surfaces_as_a_readable_start_error(self):
        from oden.tak.bridge import _DEFAULTS, TakBridge

        FakeEnrollment.fail_with = "Error generating CSR: 401, message='Unauthorized'"
        bridge = TakBridge(
            {**_DEFAULTS, "cot_url": f"ssl://{HOST}:8089", "enroll_username": USER, "enroll_password": PASSWORD}
        )
        with (
            patch.dict(
                sys.modules,
                {
                    "pytak": SimpleNamespace(CLITool=_FakeCLITool),
                    "pytak.crypto_classes": SimpleNamespace(CertificateEnrollment=FakeEnrollment),
                },
            ),
            patch("oden.tak.bridge.tak_dir", return_value=self.dest),
            self.assertRaises(ValueError) as ctx,
        ):
            await bridge.start()

        self.assertIn("401", str(ctx.exception))
        self.assertNotIn(PASSWORD, str(ctx.exception))
        self.assertEqual(_FakeCLITool.instances, [], "pytak must not be started without a cert")


if __name__ == "__main__":
    unittest.main()


class BridgeEnrollmentCaTest(unittest.IsolatedAsyncioTestCase):
    """After a QR enrollment there is no CA file: the CA the server sent with our cert is used."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = Path(self._tmp.name) / "tak"
        _CALLS.clear()
        FakeEnrollment.fail_with = None
        FakeEnrollment.days_valid = 365
        FakeEnrollment.with_ca = True
        _FakeCLITool.instances = []

    async def _start(self, **settings):
        from oden.tak.bridge import _DEFAULTS, TakBridge

        bridge = TakBridge(
            {
                **_DEFAULTS,
                "cot_url": f"tls://{HOST}:8089",
                "enroll_username": USER,
                "enroll_password": PASSWORD,
                **settings,
            }
        )
        with (
            patch.dict(
                sys.modules,
                {
                    "pytak": SimpleNamespace(CLITool=_FakeCLITool),
                    "pytak.crypto_classes": SimpleNamespace(CertificateEnrollment=FakeEnrollment),
                },
            ),
            patch("oden.tak.bridge.tak_dir", return_value=self.dest),
            patch("oden.tak.listener.start_tak_listener", return_value=None),
        ):
            await bridge.start()
            self.addCleanup(bridge.stop)
        return _FakeCLITool.instances[0].config

    async def test_enrolled_ca_is_used_to_verify_the_server(self):
        config = await self._start()
        ca_path = config.get("PYTAK_TLS_CLIENT_CAFILE")
        self.assertTrue(ca_path and ca_path.endswith("-ca.pem"))
        pem = Path(ca_path).read_bytes()
        self.assertEqual(x509.load_pem_x509_certificates(pem)[0].subject.rfc4514_string(), "CN=TAK Test CA")
        self.assertNotIn("PYTAK_TLS_DONT_VERIFY", config)

    async def test_a_configured_ca_file_wins(self):
        config = await self._start(tls_ca_cert="/etc/tak/ca.pem")
        self.assertEqual(config.get("PYTAK_TLS_CLIENT_CAFILE"), "/etc/tak/ca.pem")

    async def test_no_ca_in_the_cert_leaves_verification_to_the_system(self):
        FakeEnrollment.with_ca = False
        config = await self._start()
        self.assertNotIn("PYTAK_TLS_CLIENT_CAFILE", config)
