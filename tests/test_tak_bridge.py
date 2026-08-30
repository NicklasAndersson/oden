import importlib.util
import unittest
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


if __name__ == "__main__":
    unittest.main()
