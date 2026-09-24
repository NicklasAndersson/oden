"""Connection QR codes from TAK servers (ATAK enrollment link, iTAK server line)."""

import unittest
import unittest.mock

from aiohttp.test_utils import AioHTTPTestCase

from oden.tak.qr import parse_tak_qr
from oden.web_server import create_app

# Shaped like OpenTAKServer's QR; the token is a dummy, not a real credential.
TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhbm5hIn0.c2lnbmF0dXJl-_x"
ENROLL = f"tak://com.atakmap.app/enroll?host=tak.example.org&username=anna&token={TOKEN}"


class ParseTakQrTest(unittest.TestCase):
    def test_enrollment_link(self):
        qr = parse_tak_qr(ENROLL)
        self.assertEqual(qr.kind, "enroll")
        self.assertEqual(qr.host, "tak.example.org")
        self.assertEqual(qr.username, "anna")
        self.assertEqual(qr.token, TOKEN)
        self.assertEqual(qr.cot_url, "tls://tak.example.org:8089")

    def test_enrollment_link_tolerates_whitespace_and_encoding(self):
        qr = parse_tak_qr(f"  tak://com.atakmap.app/enroll?host=tak.example.org&username=anna%20b&token={TOKEN}\n")
        self.assertEqual(qr.username, "anna b")

    def test_api_port_in_host_does_not_become_the_cot_port(self):
        self.assertEqual(parse_tak_qr(ENROLL.replace("tak.example.org", "tak.example.org:8443")).port, 8089)
        self.assertEqual(parse_tak_qr(ENROLL.replace("tak.example.org", "tak.example.org:8089")).port, 8089)

    def test_enrollment_link_missing_token(self):
        with self.assertRaisesRegex(ValueError, "token"):
            parse_tak_qr("tak://com.atakmap.app/enroll?host=tak.example.org&username=anna")

    def test_other_tak_links_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "enrollment-länk"):
            parse_tak_qr("tak://com.atakmap.app/import?url=https://example.org/pkg.zip")

    def test_itak_server_line(self):
        qr = parse_tak_qr("Hemvärnet,tak.example.org,8089,SSL")
        self.assertEqual(qr.kind, "itak")
        self.assertEqual(qr.cot_url, "tls://tak.example.org:8089")
        self.assertEqual(qr.description, "Hemvärnet")
        self.assertEqual(qr.token, "")
        self.assertIn("inga inloggningsuppgifter", qr.summary())

    def test_itak_tcp_and_quic(self):
        self.assertEqual(parse_tak_qr("Lab,10.0.0.5,8087,TCP").cot_url, "tcp://10.0.0.5:8087")
        self.assertEqual(parse_tak_qr("Srv,tak.example.org,8090,quic").cot_url, "tls://tak.example.org:8089")

    def test_garbage(self):
        for text in ("", "hello", "a,b,c,d", "Srv,tak.example.org,notaport,SSL"):
            with self.assertRaises(ValueError):
                parse_tak_qr(text)


class TakQrApiTest(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_enrollment_qr_fills_the_form_without_saving(self):
        with unittest.mock.patch("oden.web_handlers.tak_handlers.set_config_value") as save:
            resp = await self.client.post("/api/tak/qr", json={"text": ENROLL})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["kind"], "enroll")
        self.assertEqual(
            data["fields"],
            {"cot_url": "tls://tak.example.org:8089", "enroll_username": "anna", "enroll_password": TOKEN},
        )
        save.assert_not_called()

    async def test_bad_qr_is_a_400_with_a_reason(self):
        resp = await self.client.post("/api/tak/qr", json={"text": "hello"})
        self.assertEqual(resp.status, 400)
        self.assertIn("Känner inte igen", (await resp.json())["error"])

    async def test_tak_tab_has_the_qr_section(self):
        text = await (await self.client.get("/")).text()
        self.assertIn('id="tak-qr-text"', text)
        self.assertIn("function applyTakQr", text)
