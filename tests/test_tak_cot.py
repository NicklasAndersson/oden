import datetime as dt
import unittest
import xml.etree.ElementTree as ET

from oden.tak.cot import (
    Report,
    cot_to_inbound,
    cot_type_matches,
    make_uid,
    report_to_cot,
    sanitize_token,
)

_UTC = dt.timezone.utc


def _report(**kw) -> Report:
    base = {
        "report_type": "7S",
        "tnr": "281430",
        "lat": 59.3293,
        "lon": 18.0686,
        "event_time": dt.datetime(2026, 8, 28, 14, 35, tzinfo=_UTC),
        "start_time": dt.datetime(2026, 8, 28, 14, 30, tzinfo=_UTC),
        "remarks": "7S RAPPORT\nStyrka: 3\nSlag: infanteri",
    }
    base.update(kw)
    return Report(**base)


class ReportToCot(unittest.TestCase):
    def test_basic_event_shape(self):
        root = ET.fromstring(report_to_cot(_report()))
        self.assertEqual(root.tag, "event")
        self.assertEqual(root.get("uid"), "ODEN.7S.281430")
        self.assertEqual(root.get("type"), "a-u-G")  # default affiliation
        self.assertEqual(root.get("how"), "h-g-i-g-o")

        point = root.find("point")
        self.assertAlmostEqual(float(point.get("lat")), 59.3293, places=4)
        self.assertAlmostEqual(float(point.get("lon")), 18.0686, places=4)

        self.assertEqual(root.find("detail/contact").get("callsign"), "7S 281430")
        self.assertIn("infanteri", root.find("detail/remarks").text)

    def test_callsign_prefixes_marker(self):
        root = ET.fromstring(report_to_cot(_report(), callsign="ODEN"))
        self.assertEqual(root.find("detail/contact").get("callsign"), "ODEN 7S 281430")

    def test_stale_after_event_time(self):
        root = ET.fromstring(report_to_cot(_report(), stale_seconds=600))
        time = dt.datetime.fromisoformat(root.get("time").replace("Z", "+00:00"))
        stale = dt.datetime.fromisoformat(root.get("stale").replace("Z", "+00:00"))
        self.assertEqual((stale - time).total_seconds(), 600)

    def test_affiliation_maps_to_type(self):
        root = ET.fromstring(report_to_cot(_report(affiliation="hostile")))
        self.assertEqual(root.get("type"), "a-h-G")

    def test_archive_toggle(self):
        self.assertIsNotNone(ET.fromstring(report_to_cot(_report(), archive=True)).find("detail/archive"))
        self.assertIsNone(ET.fromstring(report_to_cot(_report(), archive=False)).find("detail/archive"))

    def test_rejects_null_island(self):
        with self.assertRaises(ValueError):
            report_to_cot(_report(lat=0.0, lon=0.0))

    def test_roundtrip(self):
        inbound = cot_to_inbound(report_to_cot(_report(affiliation="hostile")))
        self.assertEqual(inbound.uid, "ODEN.7S.281430")
        self.assertEqual(inbound.cot_type, "a-h-G")
        self.assertEqual(inbound.affiliation, "hostile")
        self.assertAlmostEqual(inbound.lat, 59.3293, places=4)
        self.assertEqual(inbound.callsign, "7S 281430")
        self.assertIn("infanteri", inbound.remarks)
        self.assertFalse(inbound.is_chat)


class CotToInbound(unittest.TestCase):
    def test_none_without_point(self):
        self.assertIsNone(cot_to_inbound(b"<event version='2.0' uid='x' type='t-x-c'></event>"))

    def test_none_on_garbage(self):
        self.assertIsNone(cot_to_inbound(b"not xml"))
        self.assertIsNone(cot_to_inbound(b"<foo/>"))

    def test_none_on_out_of_range(self):
        xml = "<event uid='a' type='a-h-G'><point lat='999' lon='10'/></event>"
        self.assertIsNone(cot_to_inbound(xml))

    def test_sanitizes_callsign_for_filenames(self):
        xml = (
            "<event uid='../../etc/passwd' type='a-u-G'>"
            "<point lat='1' lon='1'/>"
            "<detail><contact callsign='bad/../name'/></detail></event>"
        )
        inbound = cot_to_inbound(xml)
        for bad in ("..", "/", "\\"):
            self.assertNotIn(bad, inbound.uid)
            self.assertNotIn(bad, inbound.callsign)

    def test_truncates_remarks(self):
        xml = (
            "<event uid='a' type='a-u-G'><point lat='1' lon='1'/>"
            f"<detail><remarks>{'x' * 9000}</remarks></detail></event>"
        )
        self.assertLessEqual(len(cot_to_inbound(xml).remarks), 4096)

    def test_detects_geochat(self):
        xml = (
            "<event uid='GeoChat.x' type='b-t-f'><point lat='1' lon='1'/>"
            "<detail><__chat chatroom='All'/><remarks>hi</remarks></detail></event>"
        )
        self.assertTrue(cot_to_inbound(xml).is_chat)

    def test_parses_custom_report_fields(self):
        xml = (
            "<event uid='Report-8S-Alpha-01' type='b-r-i-c-o'><point lat='1' lon='1'/>"
            "<detail><contact callsign='RECON_TEAM_1'/>"
            "<custom_report name='8-Line Spot Report'>"
            "<line1_size>3x Personnel</line1_size>"
            "<line3_location>11S YT 1234 5678</line3_location>"
            "</custom_report></detail></event>"
        )
        inbound = cot_to_inbound(xml)
        self.assertEqual(inbound.custom_report_name, "8-Line Spot Report")
        self.assertEqual(inbound.custom_report["line1_size"], "3x Personnel")
        self.assertEqual(inbound.custom_report["line3_location"], "11S YT 1234 5678")

    def test_no_custom_report_is_empty_dict(self):
        xml = "<event uid='a' type='a-u-G'><point lat='1' lon='1'/><detail/></event>"
        inbound = cot_to_inbound(xml)
        self.assertEqual(inbound.custom_report, {})
        self.assertEqual(inbound.custom_report_name, "")

    def test_custom_report_skips_empty_fields_and_caps_length(self):
        xml = (
            "<event uid='a' type='a-u-G'><point lat='1' lon='1'/>"
            "<detail><custom_report>"
            "<empty_line></empty_line>"
            f"<long_line>{'x' * 900}</long_line>"
            "</custom_report></detail></event>"
        )
        inbound = cot_to_inbound(xml)
        self.assertNotIn("empty_line", inbound.custom_report)
        self.assertEqual(len(inbound.custom_report["long_line"]), 512)

    def test_custom_report_field_count_is_capped(self):
        fields = "".join(f"<f{i}>v</f{i}>" for i in range(100))
        xml = f"<event uid='a' type='a-u-G'><point lat='1' lon='1'/><detail><custom_report>{fields}</custom_report></detail></event>"
        inbound = cot_to_inbound(xml)
        self.assertLessEqual(len(inbound.custom_report), 64)


class Helpers(unittest.TestCase):
    def test_sanitize_token_never_dotdot(self):
        self.assertNotIn("..", sanitize_token("../../x"))
        self.assertEqual(sanitize_token("   "), "okänd")

    def test_make_uid_strips_spaces(self):
        self.assertEqual(make_uid("7S rapport", "28 14 30"), "ODEN.7Srapport.281430")

    def test_cot_type_matches(self):
        self.assertTrue(cot_type_matches("a-h-G", ["a-f-*", "a-h-*"]))
        self.assertTrue(cot_type_matches("a-h-G", ["a-h-G"]))
        self.assertFalse(cot_type_matches("a-f-G-U-C", ["a-h-*", "a-u-*"]))


if __name__ == "__main__":
    unittest.main()
