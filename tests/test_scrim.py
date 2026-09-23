"""SCRIM vehicle reports: CoT -> ``SCRIM RAPPORT`` text.

The XML here is built inline from the shape of four real reports captured on the
user's server (see the notes in the vault), rather than from a stored fixture —
`tests/fixtures/tak/` claims its files are verbatim server captures and that
claim is worth keeping. Replace these with a real capture when one is available.
"""

import unittest

from oden.pipelines.seven_s import _link_remaining_plates
from oden.pipelines.structured_report import iter_nonempty_lines
from oden.tak.cot import cot_to_inbound
from oden.tak.scrim import canonical_plate, is_scrim_report, to_scrim_message

_STUND = "2026-09-15T11:45:42.248Z"  # 13:45:42 local -> TNR 151345


def _scrim(*, fields: str, remarks: str = "", when: str = "2026-09-15T18:09:11Z", skapad: str = "") -> object:
    """A SCRIM CoT. ``when`` is the *relay* time, deliberately later than STUND."""
    created = f' SKAPAD="{skapad}"' if skapad else ""
    return cot_to_inbound(
        f"""<event version="2.0" uid="4d5f12d7" type="a-x-X" how="h-g-i-g-o"
 time="{when}" start="{when}" stale="2027-09-15T18:09:11Z">
<point lat="59.17095" lon="17.66870" hae="9999999.0" ce="9999999.0" le="9999999.0"/>
<detail><contact callsign="SCRIM-BRGB05-151344"/>
<HVSS_DOCUMENTS><SCRIM{created}>{fields}</SCRIM></HVSS_DOCUMENTS>
<remarks>{remarks}</remarks>
<link uid="ANDROID-2cdcf555c0a02c42" parent_callsign="BRGB05" relation="p-p"/>
</detail></event>"""
    )


_FULL = (
    "<R>PHS 331</R><SAGESMAN>BRGB05</SAGESMAN><S>Ups leveransbil</S><C>Brun</C>"
    f"<STUND>{_STUND}</STUND><I>Man med tofs i håret</I><M>Ups Bil</M>"
    "<STÄLLE>33VXF5253662139</STÄLLE>"
)


def _line(message: str, label: str) -> str:
    """One field off the wire. Strips the ride-along the way the parser does — a
    naive split on "%%" would also cut at an inline one in operator text."""
    prefix = f"{label}: "
    return next((ln[len(prefix) :] for ln in iter_nonempty_lines(message) if ln.startswith(prefix)), "")


class DetectionTest(unittest.TestCase):
    def test_a_scrim_block_is_recognised(self):
        self.assertTrue(is_scrim_report(_scrim(fields=_FULL)))

    def test_an_8s_is_not_a_scrim(self):
        cot = cot_to_inbound(
            "<event uid='a' type='a-h-G'><point lat='59' lon='17'/>"
            "<detail><_8S_ POSITION='x' INFORMANT='y'/></detail></event>"
        )
        self.assertFalse(is_scrim_report(cot))

    def test_a_bare_marker_is_not_a_scrim(self):
        cot = cot_to_inbound("<event uid='a' type='a-h-G'><point lat='59' lon='17'/><detail/></event>")
        self.assertFalse(is_scrim_report(cot))


class TimeTest(unittest.TestCase):
    """Reports are relayed by hand, so the CoT time is when it reached us, not when it was seen."""

    def test_the_iso_utc_stund_becomes_a_local_tnr(self):
        message = to_scrim_message(_scrim(fields=_FULL))
        self.assertEqual(_line(message, "TNR"), "151345")  # not 1809, the relay time

    def test_stund_is_the_long_form_so_a_stale_relay_cannot_shift_the_month(self):
        """A bare DDHHMM resolves against the arrival date and rolls back at most one
        month. A real capture was relayed three months late, which would land on the
        wrong month entirely."""
        message = to_scrim_message(_scrim(fields=_FULL.replace(_STUND, "2026-06-12T15:29:17.000Z")))
        self.assertEqual(_line(message, "Stund"), "121729ZJUN2026")

    def test_epoch_skapad_is_used_when_stund_is_missing(self):
        without_stund = _FULL.replace(f"<STUND>{_STUND}</STUND>", "")
        message = to_scrim_message(_scrim(fields=without_stund, skapad="1789472742248"))
        self.assertEqual(_line(message, "TNR"), "151345")
        self.assertIn("tnr_kalla: Skapad", message)

    def test_the_relay_time_is_the_last_resort_and_says_so(self):
        bare = "<S>Pick-up</S><C>Vit</C>"
        message = to_scrim_message(_scrim(fields=bare))
        self.assertIn("tnr_kalla: event_time", message)

    def test_a_stray_number_in_skapad_is_not_read_as_a_date(self):
        bare = "<S>Pick-up</S>"
        message = to_scrim_message(_scrim(fields=bare, skapad="42"))
        self.assertIn("tnr_kalla: event_time", message)


class PlateTest(unittest.TestCase):
    def test_a_swedish_plate_with_a_space_canonicalises_like_seven_s(self):
        """The whole point: a plate seen here and in a 7S must be the same vault node."""
        self.assertEqual(canonical_plate("PHS 331"), "PHS331")
        self.assertEqual(f"[[{canonical_plate('PHS 331')}]]", _link_remaining_plates("reg PHS331").split()[-1])

    def test_a_foreign_plate_is_linked_even_though_it_is_not_swedish_format(self):
        """_FULL_PLATE_RE cannot match TDS1891B; the R field is declared, so we do not need it to."""
        self.assertEqual(canonical_plate("TDS1891B"), "TDS1891B")
        self.assertEqual(_link_remaining_plates("TDS1891B"), "TDS1891B")  # regex alone finds nothing

    def test_no_plate_observed_is_not_a_plate(self):
        for raw in ("-", "–", "", "  ", "SAKNAS", "okänd", "N/A"):
            with self.subTest(raw):
                self.assertIsNone(canonical_plate(raw))

    def test_a_sentence_typed_into_the_field_is_not_a_plate(self):
        self.assertIsNone(canonical_plate("en vit skåpbil"))

    def test_brackets_cannot_break_out_of_the_wikilink(self):
        """The value is wrapped unconditionally, so it must not be able to close the link."""
        for raw in ("X1]] [[evil", "AB1|alias", "AB1#heading", "AB1\nAB2"):
            with self.subTest(raw):
                plate = canonical_plate(raw)
                self.assertNotRegex(plate or "", r"[\[\]|#^\n]")


class ReshapeTest(unittest.TestCase):
    def test_every_scrim_letter_reaches_the_message(self):
        message = to_scrim_message(_scrim(fields=_FULL))
        self.assertEqual(_line(message, "Storlek"), "Ups leveransbil")
        self.assertEqual(_line(message, "Färg"), "Brun")
        self.assertEqual(_line(message, "Registrering"), "PHS 331")
        self.assertEqual(_line(message, "Kännetecken"), "Man med tofs i håret")
        self.assertEqual(_line(message, "Märke"), "Ups Bil")

    def test_registrering_is_written_even_when_there_is_none(self):
        """On a checklist "looked, no plate" is not the same as "field omitted"."""
        message = to_scrim_message(_scrim(fields="<S>Pick-up</S><C>Vit</C>"))
        self.assertEqual(_line(message, "Registrering"), "-")

    def test_sagesman_falls_back_to_the_sender_not_the_marker_label(self):
        without = _FULL.replace("<SAGESMAN>BRGB05</SAGESMAN>", "")
        message = to_scrim_message(_scrim(fields=without))
        self.assertEqual(_line(message, "Sagesman"), "BRGB05")  # not SCRIM-BRGB05-151344

    def test_stalle_falls_back_to_the_cot_point(self):
        without = _FULL.replace("<STÄLLE>33VXF5253662139</STÄLLE>", "")
        self.assertTrue(_line(to_scrim_message(_scrim(fields=without)), "Ställe"))

    def test_remarks_become_an_anmarkning_and_survive_verbatim(self):
        """Operators put corrections there: "Regnr rättning TOS99218 Polsk registrerad"."""
        correction = "Regnr rättning TOS99218 Polsk registrerad"
        message = to_scrim_message(_scrim(fields=_FULL, remarks=correction))
        self.assertEqual(_line(message, "Anmärkning"), correction)
        self.assertIn(f"remarks: {correction}", message)

    def test_double_escaped_newlines_become_spaces(self):
        """This plugin family escapes a newline twice, so a literal &#10; lands in the value."""
        message = to_scrim_message(_scrim(fields="<S>Pick-up</S><I>vit&amp;#10;skåpbil</I>"))
        self.assertEqual(_line(message, "Kännetecken"), "vit skåpbil")

    def test_newlines_cannot_inject_extra_fields(self):
        message = to_scrim_message(_scrim(fields="<S>Pick-up\nTNR: 010101\nRegistrering: AAA111</S>"))
        self.assertEqual(_line(message, "TNR"), "152009")  # the relay time (18:09Z = 20:09 local), not the forged one
        self.assertEqual(_line(message, "Registrering"), "-")

    def test_the_raw_ridealong_is_a_hidden_comment(self):
        message = to_scrim_message(_scrim(fields=_FULL))
        self.assertTrue(message.rstrip().endswith("%%"))
        self.assertIn("SCRIM (ATAK) rådata — oförändrad:", message)

    def test_a_percent_block_in_operator_text_cannot_truncate_the_report(self):
        """An inline %% is harmless — the comment regex anchors on %% alone on a line —
        but the raw block still neuters it so the ride-along cannot close early."""
        message = to_scrim_message(_scrim(fields="<S>slut %% här</S><M>Renault</M>"))
        self.assertEqual(_line(message, "Märke"), "Renault")  # survives the stray %%
        self.assertIn("Märke: Renault", "\n".join(iter_nonempty_lines(message)))
        self.assertIn("S: slut % % här", message)  # neutered inside the raw block


if __name__ == "__main__":
    unittest.main()
