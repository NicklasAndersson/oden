"""Regression tests over CoT captured off a live TAK Server 5.7 / ATAK-CIV 5.6.

See tests/fixtures/tak/README.md. These lock in that real client output parses
the way we expect — the synthetic tests elsewhere can drift from reality.
"""

import unittest
from pathlib import Path

from oden.tak.cot import cot_to_inbound, raw_event_type
from oden.tak.eight_s import is_8s_report, to_7s_message
from oden.tak.listener import _INBOUND_DEFAULTS, InboundFilter, build_envelope, render_observation

_FIX = Path(__file__).parent / "fixtures" / "tak"


def _load(name: str) -> bytes:
    return (_FIX / name).read_bytes()


class RealSampleTest(unittest.TestCase):
    def _filter(self) -> InboundFilter:
        return InboundFilter(dict(_INBOUND_DEFAULTS))

    def test_8s_report_parses_and_renders_all_fields(self):
        cot = cot_to_inbound(_load("8s_report.xml"))
        self.assertIsNotNone(cot)
        self.assertEqual(cot.cot_type, "a-h-G")
        self.assertEqual(cot.affiliation, "hostile")
        self.assertAlmostEqual(cot.lat, 59.3442335, places=5)
        self.assertEqual(cot.custom_report_name, "8S")
        self.assertEqual(cot.custom_report["Position"], "34V CL 3939 8179")
        self.assertEqual(cot.custom_report["Strength Type"], "En")
        self.assertEqual(cot.custom_report["Symbol"], "Rekyl T-shirt")
        self.assertEqual(cot.custom_report["Informant"], "LarsNo")
        self.assertEqual(cot.custom_report["Then"], "Somnar om")
        self.assertNotIn("Type", cot.custom_report)  # structural attr not a field

        note = render_observation(cot)
        self.assertTrue(note.startswith("TAK-OBSERVATION"))
        self.assertIn("Bifogad rapport: 8S", note)
        self.assertIn("Symbol: Rekyl T-shirt", note)
        self.assertIn("Somnar om", note)
        # server plumbing never leaks into the note
        self.assertNotIn("TAK-Server-", note)
        self.assertNotIn("flow-tags", note)

    def test_8s_report_passes_the_default_filter(self):
        self.assertTrue(self._filter().accept(cot_to_inbound(_load("8s_report.xml"))))

    def test_spi_pointer_is_accepted_but_carries_no_report(self):
        cot = cot_to_inbound(_load("spi_pointer.xml"))
        self.assertEqual(cot.cot_type, "b-m-p-s-p-i")
        self.assertEqual(cot.custom_report, {})
        self.assertTrue(self._filter().accept(cot))  # b-m-p-* is in defaults

    def test_sender_is_the_operators_device_when_the_cot_names_one(self):
        pointer = cot_to_inbound(_load("spi_pointer.xml"))
        self.assertEqual(pointer.operator_uid, "ANDROID-a3078d3cd6571a0f")  # <creator>/<link relation="p-p">
        self.assertEqual(build_envelope(pointer, "g")["envelope"]["sourceUuid"], "tak:ANDROID-a3078d3cd6571a0f")
        # The Reports plugin names no device, so an 8S falls back to its own (per-report) uid
        report = cot_to_inbound(_load("8s_report.xml"))
        self.assertEqual(report.operator_uid, "")
        self.assertEqual(build_envelope(report, "g")["envelope"]["sourceUuid"], f"tak:{report.uid}")

    def test_friendly_pli_is_filtered_out(self):
        f = self._filter()
        self.assertFalse(f.accept(cot_to_inbound(_load("friendly_pli.xml"))))
        self.assertIn("inbound_types", f.last_reject)

    def test_takproto_announcement_yields_nothing(self):
        self.assertIsNone(cot_to_inbound(_load("takproto_v.xml")))

    def test_raw_event_type_agrees_with_the_full_parse(self):
        """The cheap read must give the same type the XML parser reports."""
        for name, expected in (
            ("8s_report.xml", "a-h-G"),
            ("spi_pointer.xml", "b-m-p-s-p-i"),
            ("friendly_pli.xml", "a-f-G-U-C"),
            ("takproto_v.xml", "t-x-takp-v"),
        ):
            with self.subTest(name):
                data = _load(name)
                self.assertEqual(raw_event_type(data), expected)
                cot = cot_to_inbound(data)
                if cot is not None:  # takproto_v has no usable position
                    self.assertEqual(raw_event_type(data), cot.cot_type)

    def test_the_pli_flood_is_discarded_without_parsing(self):
        self.assertTrue(self._filter().prescreen_rejects(_load("friendly_pli.xml")))

    def test_reports_and_pointers_survive_the_prescreen(self):
        for name in ("8s_report.xml", "spi_pointer.xml"):
            with self.subTest(name):
                self.assertFalse(self._filter().prescreen_rejects(_load(name)))


if __name__ == "__main__":
    unittest.main()


class HvReportsFormatTest(unittest.TestCase):
    """The *other* 8S. Two ATAK plugins are enabled side by side across the fleet and
    both file an 8S: "8S" (com.atakmap.android.eights.plugin) flattens English keys
    into attributes under ``a-h-G``, "HV Rapporter"
    (com.atakmap.android.hvreports.plugin) nests Swedish keys as element text inside
    ``<HVSS_DOCUMENTS>`` under ``a-x-X``. Neither is "the" format."""

    def _cot(self):
        return cot_to_inbound(_load("8s_hvreports.xml"))

    def test_the_wrapper_does_not_hide_that_this_is_an_8s(self):
        """Named after <HVSS_DOCUMENTS> it would be "Hvss Documents" and never recognised."""
        cot = self._cot()
        self.assertEqual(cot.cot_type, "a-x-X")
        self.assertEqual(cot.custom_report_name, "8S")
        self.assertTrue(is_8s_report(cot))

    def test_swedish_element_fields_are_extracted(self):
        report = self._cot().custom_report
        self.assertEqual(report["SAGESMAN"], "AQEA01")
        self.assertEqual(report["STYRKA_SLAG"], "4 soldater")
        self.assertEqual(report["STÄLLE"], "33VVF6937665634")

    def test_it_reaches_the_default_filter(self):
        """a-x-X has to be in inbound_types or the report is dropped before parsing."""
        self.assertTrue(InboundFilter(dict(_INBOUND_DEFAULTS)).accept(self._cot()))

    def test_swedish_keys_map_onto_the_same_7s_fields(self):
        message = to_7s_message(self._cot())
        self.assertIn("Ställe: 33VVF6937665634", message)  # STÄLLE
        self.assertIn("Händelse: 4 soldater, Lökar", message)  # STYRKA_SLAG + SYSSELSÄTTNING
        self.assertIn("Sagesman: AQEA01", message)  # SAGESMAN
        self.assertIn("Symbol: Hv", message)
        self.assertIn("Sedan: Vila", message)  # SEDAN

    def test_the_iso_utc_timestamp_becomes_a_local_tnr(self):
        """STUND is ISO 8601 in UTC; read as local it would put the TNR two hours off."""
        message = to_7s_message(self._cot())
        self.assertIn("TNR: 121729", message)  # 2026-06-12T15:29:17Z -> 17:29 local
        self.assertIn("Stund: 121729ZJUN2026", message)

    def test_the_sender_is_the_operator_not_the_marker(self):
        cot = self._cot()
        self.assertEqual(cot.operator_callsign, "AQEA01")
        self.assertEqual(cot.operator_uid, "ANDROID-3f5372c2e13e953c")

    def test_the_two_plugins_produce_the_same_7s_shape(self):
        """Whatever the vault sees must not depend on which plugin the operator used."""
        for name in ("8s_report.xml", "8s_hvreports.xml"):
            with self.subTest(name):
                message = to_7s_message(cot_to_inbound(_load(name)))
                labels = [line.split(":")[0] for line in message.split("%%")[0].strip().splitlines() if ":" in line]
                self.assertEqual(
                    labels,
                    ["Till", "Från", "TNR", "Stund", "Ställe", "Händelse", "Symbol", "Sagesman", "Sedan"],
                )
