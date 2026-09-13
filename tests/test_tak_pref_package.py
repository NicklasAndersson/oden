"""Reading ATAK data packages.

Two kinds exist and only one of them was ever handled: a package carrying a
client cert, and a trust-only package that expects the client to enroll. The
second one used to reach ``pytak.read_pref_package``, which has no notion of it
and raised ``TypeError('stat: path should be ... not NoneType')`` from an
internal ``os.path.exists(None)``.

Certificates here are generated per test run, so nothing secret is committed.
"""

import datetime as dt
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from oden.tak.pref_package import PackageConfig, describe_package, read_data_package

_FIX = Path(__file__).parent / "fixtures" / "tak"
_CA_PASSWORD = "exempel-ca-losenord"
_CLIENT_PASSWORD = "exempel-klient-losenord"


def _self_signed(common_name: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _truststore(password: str) -> bytes:
    """A PKCS#12 holding CA certs and *no* private key, like a real TAK truststore."""
    _key, cert = _self_signed("Example TAK CA")
    return pkcs12.serialize_key_and_certificates(
        name=b"ca",
        key=None,
        cert=None,
        cas=[cert],
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode()),
    )


def _client_p12(password: str) -> bytes:
    key, cert = _self_signed("oden")
    return pkcs12.serialize_key_and_certificates(
        name=b"oden",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode()),
    )


def _zip(path: Path, members: dict[str, bytes]) -> str:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, blob in members.items():
            zf.writestr(name, blob)
    path.write_bytes(buf.getvalue())
    return str(path)


_CLIENT_PREF = """<?xml version='1.0' encoding='ASCII' standalone='yes'?>
<preferences>
  <preference version="1" name="cot_streams">
    <entry key="connectString0" class="class java.lang.String">tak.example.mil:8089:ssl</entry>
    <entry key="description0" class="class java.lang.String">Exempel TAK Server</entry>
    <entry key="{cert_key}" class="class java.lang.String">cert/clientCert.p12</entry>
    <entry key="{pass_key}" class="class java.lang.String">{password}</entry>
  </preference>
</preferences>
"""


class DataPackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "out"

    def _enrollment_zip(self, **members: bytes) -> str:
        return _zip(
            self.tmp / "enroll.zip",
            {
                "config.pref": (_FIX / "enrollment_package.pref").read_bytes(),
                "caCert.p12": _truststore(_CA_PASSWORD),
                **members,
            },
        )

    def test_enrollment_package_yields_ca_and_asks_for_enrollment(self):
        package = read_data_package(self._enrollment_zip(), self.out)

        self.assertEqual(package.cot_url, "ssl://tak.example.mil:8089")
        self.assertEqual(package.description, "Exempel TAK Server")
        self.assertTrue(package.needs_enrollment)
        self.assertEqual(package.kind, "enrollment")
        self.assertEqual(package.client_cert, "")

        pem = Path(package.ca_pem).read_text()
        self.assertIn("-----BEGIN CERTIFICATE-----", pem)
        self.assertNotIn("PRIVATE KEY", pem)  # a truststore has none

    def test_extracted_key_material_is_not_world_readable(self):
        package = read_data_package(self._enrollment_zip(), self.out)
        self.assertEqual(Path(package.ca_pem).stat().st_mode & 0o777, 0o600)

    def test_ca_location_with_a_directory_prefix_resolves_by_basename(self):
        """The .pref says cert/caCert.p12 while the zip has it at the root."""
        package = read_data_package(self._enrollment_zip(), self.out)
        self.assertTrue(package.ca_pem)

    def test_client_cert_package_needs_no_enrollment(self):
        for cert_key, pass_key in (
            ("certificateLocation", "clientPassword"),  # what ATAK writes
            ("certificateLocation0", "clientPassword0"),  # what pytak's own generator writes
        ):
            with self.subTest(cert_key=cert_key):
                pref = _CLIENT_PREF.format(cert_key=cert_key, pass_key=pass_key, password=_CLIENT_PASSWORD)
                path = _zip(
                    self.tmp / f"client-{cert_key}.zip",
                    {"config.pref": pref.encode(), "cert/clientCert.p12": _client_p12(_CLIENT_PASSWORD)},
                )
                package = read_data_package(path, self.out)

                self.assertFalse(package.needs_enrollment)
                self.assertEqual(package.kind, "klientcert")
                self.assertEqual(package.client_password, _CLIENT_PASSWORD)
                self.assertTrue(Path(package.client_cert).is_file())
                self.assertEqual(Path(package.client_cert).stat().st_mode & 0o777, 0o600)

    def test_missing_pref_file_is_reported_in_swedish(self):
        path = _zip(self.tmp / "nopref.zip", {"readme.txt": b"hej"})
        with self.assertRaises(ValueError) as ctx:
            read_data_package(path, self.out)
        self.assertIn(".pref", str(ctx.exception))

    def test_wrong_ca_password_names_the_culprit(self):
        path = _zip(
            self.tmp / "badpw.zip",
            {
                "config.pref": (_FIX / "enrollment_package.pref").read_bytes(),
                "caCert.p12": _truststore("fel-losenord"),
            },
        )
        with self.assertRaises(ValueError) as ctx:
            read_data_package(path, self.out)
        self.assertIn("caPassword", str(ctx.exception))

    def test_missing_connect_string_is_reported(self):
        pref = b"<?xml version='1.0'?><preferences><preference><entry key='count'>1</entry></preference></preferences>"
        path = _zip(self.tmp / "nourl.zip", {"config.pref": pref})
        with self.assertRaises(ValueError) as ctx:
            read_data_package(path, self.out)
        self.assertIn("connectString", str(ctx.exception))

    def test_ca_file_named_in_the_pref_but_absent_from_the_zip(self):
        path = _zip(self.tmp / "noca.zip", {"config.pref": (_FIX / "enrollment_package.pref").read_bytes()})
        with self.assertRaises(ValueError) as ctx:
            read_data_package(path, self.out)
        self.assertIn("caCert.p12", str(ctx.exception))

    def test_a_missing_package_file_is_not_a_traceback(self):
        with self.assertRaises(ValueError):
            read_data_package(str(self.tmp / "finns-inte.zip"), self.out)

    def test_a_non_zip_is_not_a_traceback(self):
        path = self.tmp / "junk.zip"
        path.write_bytes(b"inte en zip")
        with self.assertRaises(ValueError):
            read_data_package(str(path), self.out)


class BuildConfigTest(unittest.TestCase):
    """The reported bug, at the layer the operator actually hits."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        import oden.tak.bridge as bridge

        self.bridge_mod = bridge
        original = bridge.tak_dir
        bridge.tak_dir = lambda: self.tmp / "out"
        self.addCleanup(setattr, bridge, "tak_dir", original)

        self.package = _zip(
            self.tmp / "enroll.zip",
            {
                "config.pref": (_FIX / "enrollment_package.pref").read_bytes(),
                "caCert.p12": _truststore(_CA_PASSWORD),
            },
        )

    def _config(self, **overrides):
        settings = {**self.bridge_mod._DEFAULTS, "enabled": True, "pref_package": self.package, **overrides}
        return self.bridge_mod.TakBridge(settings)._build_config()

    def test_trust_only_package_without_credentials_explains_itself(self):
        with self.assertRaises(ValueError) as ctx:
            self._config()
        message = str(ctx.exception)
        self.assertIn("enrollment", message)
        self.assertIn("användarnamn", message)
        # The whole point: not TypeError('stat: path should be ... not NoneType')
        self.assertNotIsInstance(ctx.exception, TypeError)

    def test_username_without_password_says_the_password_is_missing(self):
        with self.assertRaises(ValueError) as ctx:
            self._config(enroll_username="oden")
        self.assertIn("lösenord", str(ctx.exception))

    def test_credentials_produce_an_enrollment_config(self):
        config = self._config(enroll_username="oden", enroll_password="hemligt")

        self.assertEqual(config.get("COT_URL"), "ssl://tak.example.mil:8089")
        self.assertEqual(config.get("PYTAK_TLS_CERT_ENROLLMENT_USERNAME"), "oden")
        self.assertEqual(config.get("PYTAK_TLS_CERT_ENROLLMENT_PASSWORD"), "hemligt")
        self.assertTrue(Path(config.get("PYTAK_TLS_CLIENT_CAFILE")).is_file())
        # Set explicitly, or pytak generates one and prints it to stdout each connect.
        self.assertTrue(config.get("PYTAK_TLS_CERT_ENROLLMENT_PASSPHRASE"))

    def test_env_var_wins_over_the_stored_password_when_actually_set(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"ODEN_TAK_ENROLL_PASSWORD": "fran-miljon"}):
            config = self._config(enroll_username="oden", enroll_password="fran-db")
        self.assertEqual(config.get("PYTAK_TLS_CERT_ENROLLMENT_PASSWORD"), "fran-miljon")

    def test_stored_password_is_used_when_the_env_var_is_absent(self):
        import os
        from unittest.mock import patch

        # The env var *name* always has a default, so the stored value must still
        # be reachable — it was not before this fix.
        with patch.dict(os.environ, {}, clear=True):
            config = self._config(enroll_username="oden", enroll_password="fran-db")
        self.assertEqual(config.get("PYTAK_TLS_CERT_ENROLLMENT_PASSWORD"), "fran-db")

    def test_an_explicit_cot_url_still_overrides_the_package(self):
        config = self._config(enroll_username="o", enroll_password="p", cot_url="tls://annan:8089")
        self.assertEqual(config.get("COT_URL"), "tls://annan:8089")


class ConnectStringTest(unittest.TestCase):
    def test_protocol_comes_from_the_connect_string(self):
        from oden.tak.pref_package import _connect_string_to_url

        self.assertEqual(_connect_string_to_url("tak.example.mil:8089:ssl"), "ssl://tak.example.mil:8089")
        self.assertEqual(_connect_string_to_url("10.0.0.1:8087:tcp"), "tcp://10.0.0.1:8087")

    def test_a_malformed_connect_string_is_reported(self):
        from oden.tak.pref_package import _connect_string_to_url

        for bad in ("tak.example.mil", "tak.example.mil:8089", "::ssl"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _connect_string_to_url(bad)


class DescribePackageTest(unittest.TestCase):
    def test_trust_only_package_says_what_is_still_needed(self):
        text = describe_package(PackageConfig(cot_url="ssl://h:8089", description="MRM", needs_enrollment=True))
        self.assertIn("enrollment-användarnamn", text)

    def test_client_cert_package_says_it_is_ready(self):
        text = describe_package(PackageConfig(cot_url="ssl://h:8089", client_cert="/tmp/c.p12"))
        self.assertIn("Spara", text)


if __name__ == "__main__":
    unittest.main()
