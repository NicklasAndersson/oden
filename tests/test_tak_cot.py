import datetime as dt
import unittest
import xml.etree.ElementTree as ET

from oden.tak.cot import (
    UID_PREFIX,
    CotTypeMatcher,
    Report,
    cot_to_inbound,
    cot_type_matches,
    make_uid,
    raw_event_type,
    report_to_cot,
    sanitize_token,
    self_pli_cot,
)
from oden.tak.listener import InboundFilter

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

    def test_a_container_tag_does_not_become_the_report_name(self):
        """HV Rapporter wraps the report: <HVSS_DOCUMENTS><_8S_>…. Named after the
        wrapper it would be "Hvss Documents" and never recognised as an 8S."""
        xml = (
            "<event uid='a' type='a-x-X'><point lat='1' lon='1'/>"
            "<detail><WRAPPER><_8S_><SAGESMAN>AQEA01</SAGESMAN></_8S_></WRAPPER></detail></event>"
        )
        inbound = cot_to_inbound(xml)
        self.assertEqual(inbound.custom_report_name, "8S")
        self.assertEqual(inbound.custom_report["SAGESMAN"], "AQEA01")

    def test_a_wrapper_carrying_attributes_names_itself(self):
        """Attributes mean it holds data, so it is the report — not a container."""
        xml = (
            "<event uid='a' type='a-u-G'><point lat='1' lon='1'/>"
            "<detail><my_report SIZE='3x'><inner><x>1</x></inner></my_report></detail></event>"
        )
        self.assertEqual(cot_to_inbound(xml).custom_report_name, "My Report")

    def test_unwrapping_stops_at_the_innermost_container(self):
        xml = (
            "<event uid='a' type='a-u-G'><point lat='1' lon='1'/>"
            "<detail><a><b><_8S_><SAGESMAN>X</SAGESMAN></_8S_></b></a></detail></event>"
        )
        self.assertEqual(cot_to_inbound(xml).custom_report_name, "8S")

    def test_arbitrary_wrapper_tag_is_not_hardcoded(self):
        # Different template, different root tag name, no "custom_report" anywhere.
        xml = (
            "<event uid='a' type='a-u-G'><point lat='1' lon='1'/>"
            "<detail><eight_line_report>"
            "<size>3x Personnel</size>"
            "</eight_line_report></detail></event>"
        )
        inbound = cot_to_inbound(xml)
        self.assertEqual(inbound.custom_report["size"], "3x Personnel")
        self.assertEqual(inbound.custom_report_name, "Eight Line Report")  # humanized tag, no name attr

    def test_attribute_based_fields(self):
        # Some templates put the value in an attribute, keyed by name/label, not element text.
        xml = (
            "<event uid='a' type='a-u-G'><point lat='1' lon='1'/>"
            "<detail><atak_report>"
            "<field name='Size' value='3x Personnel'/>"
            "<field label='Activity' value='Staging equipment'/>"
            "</atak_report></detail></event>"
        )
        inbound = cot_to_inbound(xml)
        self.assertEqual(inbound.custom_report["Size"], "3x Personnel")
        self.assertEqual(inbound.custom_report["Activity"], "Staging equipment")

    def test_fields_flattened_into_wrapper_attributes(self):
        # The 8S report form: every field is an attribute on one <_8S_> element.
        xml = (
            "<event uid='8S.x' type='a-h-G'><point lat='59.34' lon='18.17'/>"
            "<detail><contact callsign='8S-LarsNo-1'/>"
            "<usericon iconsetpath='x/red-pushpin.png'/>"
            "<_8S_ POSITION='34V CL 3939 8179' STRENGTH_TYPE='En' SYMBOL='Rekyl T-shirt' "
            "INFORMANT='LarsNo' THEN='Somnar om'/>"
            "<_flow-tags_ TAK-Server-7e3cba2a3cd544e7bbed2c667731cadc='2026-08-31T19:42:06Z'/>"
            "</detail></event>"
        )
        inbound = cot_to_inbound(xml)
        self.assertEqual(inbound.custom_report_name, "8S")
        self.assertEqual(inbound.custom_report["Position"], "34V CL 3939 8179")
        self.assertEqual(inbound.custom_report["Symbol"], "Rekyl T-shirt")
        self.assertNotIn("Type", inbound.custom_report)  # structural attr excluded
        # _flow-tags_ (server plumbing) contributes nothing
        self.assertNotIn("TAK-Server-7e3cba2a3cd544e7bbed2c667731cadc", str(inbound.custom_report))

    def test_spi_pointer_has_no_report_fields(self):
        # ATAK digital-pointer (SPI): contact/link/hideLabel/creator/_flow-tags_ only.
        xml = (
            "<event uid='A.SPI1' type='b-m-p-s-p-i'><point lat='59.34' lon='18.17'/>"
            "<detail><contact callsign='DOWNY.DP1'/>"
            "<link uid='A' type='a-f-G-U-C' relation='p-p'/>"
            "<hideLabel/><creator uid='A' type='a-f-G-U-C'/>"
            "<_flow-tags_ TAK-Server-abc='t'/></detail></event>"
        )
        inbound = cot_to_inbound(xml)
        self.assertEqual(inbound.custom_report, {})
        self.assertEqual(inbound.custom_report_name, "")

    def test_ignores_standard_cot_metadata(self):
        # Every ATAK client attaches these regardless of report content; must never
        # be mistaken for report fields.
        xml = (
            "<event uid='a' type='a-u-G'><point lat='1' lon='1'/><detail>"
            "<takv os='30' version='4.11' device='Samsung' platform='ATAK-CIV'/>"
            "<precisionlocation geopointsrc='GPS' altsrc='GPS'/>"
            "<status battery='87'/>"
            "<__group name='Cyan' role='Team Member'/>"
            "<custom_report><line1_size>3x Personnel</line1_size></custom_report>"
            "</detail></event>"
        )
        inbound = cot_to_inbound(xml)
        self.assertEqual(inbound.custom_report, {"line1_size": "3x Personnel"})


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


class RawEventTypeTest(unittest.TestCase):
    """The cheap pre-screen read. None always means "parse it properly"."""

    def test_reads_the_root_type(self):
        self.assertEqual(raw_event_type(b'<event uid="x" type="a-f-G-U-C"><point/></event>'), "a-f-G-U-C")

    def test_reads_single_quoted_attributes(self):
        self.assertEqual(raw_event_type(b"<event uid='x' type='a-h-G'><point/></event>"), "a-h-G")

    def test_type_last_and_across_newlines(self):
        self.assertEqual(raw_event_type(b'<event\n  uid="x"\n  how="m-g"\n  type="b-a-o-tbl"\n>'), "b-a-o-tbl")

    def test_xml_declaration_is_allowed_before_the_root(self):
        self.assertEqual(raw_event_type(b'<?xml version="1.0"?>\n<event uid="x" type="a-h-G"/>'), "a-h-G")

    def test_a_nested_type_cannot_be_mistaken_for_the_root(self):
        # The root is the flood type; a nested link carries a whitelisted one.
        xml = b'<event uid="x" type="a-f-G-U-C"><detail><link type="a-h-G" relation="p-p"/></detail></event>'
        self.assertEqual(raw_event_type(xml), "a-f-G-U-C")

    def test_nested_type_alone_is_undecidable(self):
        self.assertIsNone(raw_event_type(b'<event uid="x"><detail><link type="a-h-G"/></detail></event>'))

    def test_a_literal_gt_inside_a_value_does_not_end_the_tag(self):
        self.assertEqual(raw_event_type(b'<event uid="a>b" type="a-h-G"/>'), "a-h-G")

    def test_entities_are_left_to_elementtree(self):
        # a-f&#45;G expands to a-f-G, which IS whitelisted — must not be judged here.
        self.assertIsNone(raw_event_type(b'<event uid="x" type="a-f&#45;G"/>'))

    def test_a_comment_before_the_root_is_undecidable(self):
        xml = b'<!-- <event type="a-f-G-U-C"/> --><event uid="x" type="a-h-G"/>'
        self.assertIsNone(raw_event_type(xml))

    def test_byte_order_mark_is_undecidable(self):
        self.assertIsNone(raw_event_type(b'\xef\xbb\xbf<event uid="x" type="a-h-G"/>'))

    def test_another_element_named_like_event(self):
        self.assertIsNone(raw_event_type(b'<eventlog type="a-h-G"/>'))
        self.assertIsNone(raw_event_type(b'<cot:event uid="x" type="a-h-G"/>'))

    def test_no_type_attribute(self):
        self.assertIsNone(raw_event_type(b'<event uid="x"><point/></event>'))

    def test_protobuf_and_non_bytes_are_undecidable(self):
        self.assertIsNone(raw_event_type(b"\xbf\x01\xbf\x12\x0ctakproto"))
        self.assertIsNone(raw_event_type('<event uid="x" type="a-h-G"/>'))  # str, not bytes
        self.assertIsNone(raw_event_type(object()))
        self.assertIsNone(raw_event_type(None))

    def test_a_type_beyond_the_scanned_head_is_undecidable(self):
        padded = b'<event uid="' + b"x" * 600 + b'" type="a-h-G"/>'
        self.assertIsNone(raw_event_type(padded))

    def test_a_truncated_read_is_undecidable(self):
        self.assertIsNone(raw_event_type(b'<event uid="x" ty'))


class CotTypeMatcherTest(unittest.TestCase):
    """The compiled matcher must agree with cot_type_matches, the reference."""

    _PATTERNS = [
        ["a-f-G", "a-h-*", "a-n-G", "a-u-*", "b-m-p-*", "b-a-*"],
        [],
        ["*"],
        ["a-h-G"],
        [" a-u-* ", "", "  "],
    ]
    _TYPES = [
        "a-f-G",
        "a-f-G-U-C",
        "a-h-G",
        "a-h-G-U-C-F",
        "a-n-G",
        "a-u-G",
        "b-m-p-s-p-i",
        "b-a-o-tbl",
        "t-x-takp-v",
        "",
    ]

    def test_agrees_with_the_reference_implementation(self):
        for patterns in self._PATTERNS:
            matcher = CotTypeMatcher.from_patterns(patterns)
            for cot_type in self._TYPES:
                with self.subTest(patterns=patterns, cot_type=cot_type):
                    self.assertEqual(matcher.matches(cot_type), cot_type_matches(cot_type, patterns))

    def test_no_patterns_matches_nothing_by_itself(self):
        # The caller gates on the pattern list being non-empty, as accept() does.
        self.assertFalse(CotTypeMatcher.from_patterns([]).matches("a-h-G"))


if __name__ == "__main__":
    unittest.main()


class SelfPliTest(unittest.TestCase):
    """Oden's own position report. Without it Oden is unaddressable: a directed CoT
    reaches only the callsigns in <marti><dest>, and ATAK builds that picker from
    position reports it has seen."""

    def _pli(self, **kw):
        defaults = {"callsign": "ODEN", "lat": 59.3293, "lon": 18.0686}
        return ET.fromstring(self_pli_cot(**{**defaults, **kw}))

    def test_it_looks_like_an_ordinary_friendly_client(self):
        event = self._pli()
        self.assertEqual(event.get("type"), "a-f-G-U-C")
        self.assertEqual(event.find("detail/contact").get("callsign"), "ODEN")

    def test_the_contact_carries_an_endpoint(self):
        """Without it a client plots a marker instead of listing a reachable contact."""
        self.assertEqual(self._pli().find("detail/contact").get("endpoint"), "*:-1:stcp")

    def test_team_and_role_are_carried_so_team_traffic_arrives(self):
        detail = self._pli(team="Orange", role="HQ").find("detail/__group")
        self.assertEqual(detail.get("name"), "Orange")
        self.assertEqual(detail.get("role"), "HQ")

    def test_the_uid_is_stable_so_the_contact_updates_instead_of_multiplying(self):
        first, second = self._pli().get("uid"), self._pli().get("uid")
        self.assertEqual(first, second)

    def test_our_own_pli_is_dropped_when_the_server_reflects_it_back(self):
        """The uid must start with UID_PREFIX or Oden would import itself every minute."""
        cot = cot_to_inbound(self_pli_cot(callsign="ODEN", lat=59.3, lon=18.0))
        self.assertTrue(cot.uid.startswith(UID_PREFIX))
        f = InboundFilter({"inbound_types": ["a-f-G-U-C"]})
        self.assertFalse(f.accept(cot))
        self.assertIn("eko", f.last_reject)

    def test_stale_is_in_the_future_so_the_contact_survives_one_missed_publish(self):
        event = self._pli(stale_seconds=120)
        start = dt.datetime.fromisoformat(event.get("start").replace("Z", "+00:00"))
        stale = dt.datetime.fromisoformat(event.get("stale").replace("Z", "+00:00"))
        self.assertEqual((stale - start).total_seconds(), 120)

    def test_a_missing_position_is_refused_rather_than_published_as_null_island(self):
        with self.assertRaises(ValueError):
            self_pli_cot(callsign="ODEN", lat=0.0, lon=0.0)

    def test_a_hostile_callsign_cannot_inject_xml(self):
        event = self._pli(callsign='x"/><script>')
        self.assertNotIn("<script>", event.find("detail/contact").get("callsign"))


# Constructed routes (not captured from a device): waypoints nested in <route>, and
# directly under <detail> with <link_attr>, the two shapes clients use.
_ROUTE_NESTED = """<event version="2.0" uid="ROUTE-ALPHA-PATROL-01" type="b-m-r" time="2026-09-24T14:00:00Z">
  <point lat="59.329300" lon="18.068600" hae="45.0" ce="10.0" le="10.0" />
  <detail>
    <contact callsign="RUTT ALPHA PATRULL"/>
    <strokeColor value="-65536"/>
    <strokeWeight value="3.0"/>
    <route routetype="Infiltration" method="Driving" order="Ascending">
      <link uid="WP-01-START" type="b-m-p-s-p-loc" relation="p-p" callsign="START POINT"/>
      <link uid="WP-02-CHECKPOINT" type="b-m-p-s-p-loc" relation="p-p" callsign="CP 1"/>
      <link uid="WP-03-OBJECTIVE" type="b-m-p-s-p-loc" relation="p-p" callsign="OBJ BRAVO"/>
    </route>
    <remarks>Primär framryckningsväg för fordon.</remarks>
  </detail>
</event>"""

_ROUTE_FLAT = (
    '<event uid="r1" type="b-m-r" time="2026-09-24T14:00:00Z"><point lat="59.3" lon="18.0"/><detail>'
    '<link uid="w1" callsign="SP" type="b-m-p-w" point="59.30,18.00" relation="c"/>'
    '<link uid="w2" callsign="CP1" type="b-m-p-c" point="59.31,18.01" relation="c"/>'
    '<link uid="w3" callsign="OBJ" type="b-m-p-w" point="59.32,18.02" relation="c"/>'
    '<link_attr method="Driving" routetype="Primary" direction="Infil"/>'
    '<strokeColor value="-1"/><strokeWeight value="3.0"/>'
    '<contact callsign="Route 1"/><link type="a-f-G-U-C" uid="ANDROID-x" parent_callsign="ALPHA" relation="p-p"/>'
    "</detail></event>"
)


class RouteAndDuplicateFieldTest(unittest.TestCase):
    def test_a_route_is_named_route_and_keeps_every_waypoint(self):
        route = cot_to_inbound(_ROUTE_NESTED)
        self.assertEqual(route.custom_report_name, "Rutt")
        self.assertEqual(route.custom_report["Punkter"], "START POINT → CP 1 → OBJ BRAVO")
        self.assertEqual(route.custom_report["Routetype"], "Infiltration")
        self.assertNotIn("strokeWeight", route.custom_report)
        # A waypoint link is not the route's creator.
        self.assertEqual(route.operator_uid, "")

    def test_flat_route_with_link_attr(self):
        route = cot_to_inbound(_ROUTE_FLAT)
        self.assertEqual(route.custom_report_name, "Rutt")
        self.assertEqual(route.custom_report["Punkter"], "SP → CP1 → OBJ")
        self.assertEqual(route.custom_report["Method"], "Driving")
        self.assertEqual((route.operator_uid, route.operator_callsign), ("ANDROID-x", "ALPHA"))

    def test_style_tags_never_name_a_report(self):
        xml = (
            "<event uid='a' type='a-h-G'><point lat='1' lon='1'/><detail>"
            "<strokeWeight value='3.0'/><strokeStyle value='solid'/>"
            "<spot_report><size>3</size><activity>gräver</activity></spot_report></detail></event>"
        )
        self.assertEqual(cot_to_inbound(xml).custom_report_name, "Spot Report")

    def test_repeated_fields_are_numbered_not_dropped(self):
        xml = (
            "<event uid='a' type='a-h-G'><point lat='1' lon='1'/><detail><vehicles>"
            "<vehicle>BTR-80</vehicle><vehicle>T-72</vehicle><vehicle>BTR-80</vehicle><vehicle>Ural</vehicle>"
            "</vehicles></detail></event>"
        )
        fields = cot_to_inbound(xml).custom_report
        # A repeated identical value is not repeated.
        self.assertEqual(fields, {"vehicle": "BTR-80", "vehicle 2": "T-72", "vehicle 3": "Ural"})
