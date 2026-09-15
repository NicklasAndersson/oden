"""SCRIM pipeline: ``SCRIM RAPPORT`` text -> a SCRIM note in the vault."""

import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from oden import config as cfg
from oden.pipelines.scrim import ScrimPipeline, is_scrim_message, parse_scrim_report

_TIMESTAMP = int(datetime.datetime(2026, 9, 15, 20, 9, 11, tzinfo=cfg.TIMEZONE).timestamp() * 1000)
_SERVER_RECEIVED = int(datetime.datetime(2026, 9, 15, 20, 9, 15, tzinfo=cfg.TIMEZONE).timestamp() * 1000)


def _make_msg_data(
    *,
    registrering="PHS 331",
    stalle="33VXF5253662139",
    kannetecken="Man med tofs i håret",
    anmarkning=None,
    group="inkorg",
    message_override=None,
):
    optional = "".join(
        f"{label}: {value}\n"
        for label, value in (
            ("Registrering", registrering),
            ("Kännetecken", kannetecken),
            ("Anmärkning", anmarkning),
        )
        if value is not None
    )
    stalle_line = f"Ställe: {stalle}\n" if stalle is not None else ""
    message = message_override or (
        "SCRIM RAPPORT\nTNR: 151345\nStund: 151345ZSEP2026\n"
        f"{stalle_line}Storlek: Ups leveransbil\nFärg: Brun\n{optional}Märke: Ups Bil\nSagesman: BRGB05\n"
    )
    return {
        "envelope": {
            "sourceName": "BRGB05",
            "sourceNumber": "tak:ANDROID-2cdcf555c0a02c42",
            "sourceUuid": "tak:ANDROID-2cdcf555c0a02c42",
            "timestamp": _TIMESTAMP,
            "serverReceivedTimestamp": _SERVER_RECEIVED,
            "dataMessage": {
                "message": message,
                "groupV2": {"name": group, "id": "oden-tak-inbound"},
                "attachments": [],
            },
        }
    }


class ScrimHelpersTest(unittest.TestCase):
    def test_recognises_its_own_header(self):
        self.assertTrue(is_scrim_message("SCRIM RAPPORT\nTNR: 151345"))
        self.assertFalse(is_scrim_message("7S RAPPORT\nTill: A"))

    def test_a_header_with_no_description_is_refused(self):
        """A bare header must not produce an empty vehicle note."""
        with self.assertRaises(ValueError):
            parse_scrim_report("SCRIM RAPPORT\nTNR: 151345\nStund: 151345ZSEP2026\n")

    def test_missing_stund_is_refused(self):
        with self.assertRaises(ValueError):
            parse_scrim_report("SCRIM RAPPORT\nTNR: 151345\nFärg: Brun\n")


class ScrimPipelineRunTest(unittest.IsolatedAsyncioTestCase):
    def _app_state(self, mock_get_app_state):
        app_state = Mock()
        app_state.resolve_contact_name.return_value = "BRGB05"
        mock_get_app_state.return_value = app_state

    async def _run(self, msg_data, tmpdir, **settings):
        pipeline = ScrimPipeline()
        with (
            patch("oden.config.VAULT_PATH", tmpdir),
            patch("oden.config.GROUP_SPLIT_ENABLED", False),
            patch("oden.config.PIPELINE_SETTINGS", settings),
        ):
            handled = await pipeline.run(msg_data=msg_data, reader=AsyncMock(), writer=AsyncMock())
        return pipeline, handled

    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_run_handles_scrim_and_writes_spec_file(self, mock_get_app_state):
        self._app_state(mock_get_app_state)
        with tempfile.TemporaryDirectory() as tmpdir:
            _, handled = await self._run(_make_msg_data(anmarkning="Regnr rättning TOS99218"), tmpdir)
            self.assertTrue(handled)
            output = Path(tmpdir) / "TNR151345.md"
            self.assertTrue(output.exists())
            content = output.read_text(encoding="utf-8")

        self.assertIn("typ: SCRIM-rapport", content)
        self.assertIn('tnr: "151345"', content)
        # The observation time from Stund, not the 20:09 relay time.
        self.assertIn('tidpunkt: "2026-09-15T13:45:00"', content)
        self.assertIn('regnr: "PHS331"', content)
        self.assertIn("sagesman: BRGB05", content)
        self.assertIn('plats: "33VXF5253662139"', content)
        self.assertIn("lat: ", content)
        self.assertIn("**Registrering:** [[PHS331]]", content)
        self.assertIn("**Storlek:** Ups leveransbil", content)
        self.assertIn("**Färg:** Brun", content)
        self.assertIn("**Märke/modell:** Ups Bil", content)
        self.assertIn("**Anmärkning:** Regnr rättning TOS99218", content)

    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_run_renders_a_dash_and_omits_regnr_when_no_plate(self, mock_get_app_state):
        self._app_state(mock_get_app_state)
        with tempfile.TemporaryDirectory() as tmpdir:
            await self._run(_make_msg_data(registrering="-"), tmpdir)
            content = (Path(tmpdir) / "TNR151345.md").read_text(encoding="utf-8")

        self.assertIn("**Registrering:** –", content)  # observed: no plate
        self.assertNotIn("regnr:", content)  # but nothing to key an entity on

    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_run_keeps_an_unusable_registration_as_text_and_warns(self, mock_get_app_state):
        self._app_state(mock_get_app_state)
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline, _ = await self._run(_make_msg_data(registrering="en vit skåpbil"), tmpdir)
            content = (Path(tmpdir) / "TNR151345.md").read_text(encoding="utf-8")

        self.assertNotIn("[[", content.split("**Registrering:**")[1].split("\n")[0])
        self.assertEqual(pipeline.last_warnings[0]["field"], "registrering")

    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_run_omits_coordinates_when_there_is_no_position(self, mock_get_app_state):
        self._app_state(mock_get_app_state)
        with tempfile.TemporaryDirectory() as tmpdir:
            await self._run(_make_msg_data(stalle=None), tmpdir)
            content = (Path(tmpdir) / "TNR151345.md").read_text(encoding="utf-8")

        for key in ("plats:", "lat:", "lon:", "location:"):
            self.assertNotIn(key, content)  # never null or 0,0
        self.assertNotIn("**Ställe:**", content)

    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_run_links_a_swedish_plate_mentioned_in_kannetecken(self, mock_get_app_state):
        self._app_state(mock_get_app_state)
        with tempfile.TemporaryDirectory() as tmpdir:
            await self._run(_make_msg_data(kannetecken="liknar ABC123"), tmpdir)
            content = (Path(tmpdir) / "TNR151345.md").read_text(encoding="utf-8")
        self.assertIn("**Kännetecken:** liknar [[ABC123]]", content)

    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_run_does_not_link_the_make_because_a_brand_is_not_an_identifier(self, mock_get_app_state):
        """FORMAT_SPEC §6.2: make/model alone is context, not an identifier."""
        self._app_state(mock_get_app_state)
        message = (
            "SCRIM RAPPORT\nTNR: 151345\nStund: 151345ZSEP2026\n"
            "Färg: Vit\nRegistrering: -\nMärke: ABC123\nSagesman: BRGB05\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            await self._run(_make_msg_data(message_override=message), tmpdir)
            content = (Path(tmpdir) / "TNR151345.md").read_text(encoding="utf-8")
        self.assertIn("**Märke/modell:** ABC123", content)
        self.assertNotIn("[[ABC123]]", content)

    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_run_respects_vault_subdir_setting(self, mock_get_app_state):
        self._app_state(mock_get_app_state)
        with tempfile.TemporaryDirectory() as tmpdir:
            await self._run(
                _make_msg_data(),
                tmpdir,
                scrim={"vault_subdir_enabled": True, "vault_subdir": "fordon"},
            )
            self.assertTrue((Path(tmpdir) / "fordon" / "TNR151345.md").exists())

    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_run_skips_a_non_scrim_message(self, mock_get_app_state):
        self._app_state(mock_get_app_state)
        with tempfile.TemporaryDirectory() as tmpdir:
            _, handled = await self._run(_make_msg_data(message_override="7S RAPPORT\nTill: A\n"), tmpdir)
            self.assertFalse(handled)

    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_run_keeps_the_raw_ridealong_as_a_hidden_comment(self, mock_get_app_state):
        self._app_state(mock_get_app_state)
        message = (
            "SCRIM RAPPORT\nTNR: 151345\nStund: 151345ZSEP2026\nFärg: Brun\nSagesman: BRGB05\n"
            "\n%%\nSCRIM (ATAK) rådata — oförändrad:\nC: Brun\ntnr_kalla: STUND\n%%"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            await self._run(_make_msg_data(message_override=message), tmpdir)
            content = (Path(tmpdir) / "TNR151345.md").read_text(encoding="utf-8")
        self.assertIn("tnr_kalla: STUND", content)
        self.assertTrue(content.rstrip().endswith("%%"))


if __name__ == "__main__":
    unittest.main()
