import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from oden import config as cfg
from oden.pipelines.fors import ForsPipeline, is_fors_message, parse_fors_report

_TIMESTAMP = int(datetime.datetime(2026, 6, 24, 15, 31, 5, tzinfo=cfg.TIMEZONE).timestamp() * 1000)
_SERVER_RECEIVED_TIMESTAMP = int(datetime.datetime(2026, 6, 24, 15, 31, 9, tzinfo=cfg.TIMEZONE).timestamp() * 1000)


def _make_msg_data(
    *,
    group="7s-test",
    tnr="241330",
):
    return {
        "envelope": {
            "sourceName": "Nicklas",
            "sourceNumber": "+46701234567",
            "sourceUuid": "dd1bac1d-b955-4ac0-9d53-14053c4fe69f",
            "timestamp": _TIMESTAMP,
            "serverReceivedTimestamp": _SERVER_RECEIVED_TIMESTAMP,
            "dataMessage": {
                "message": (
                    f"FORS-RAPPORT\nTill: TILL\nFrån: FRA\nTNR: {tnr}\n\n"
                    "F – FÖRBANDETS POSITION\nUPK3\n\n"
                    "O – ORIENTERING\nFI är övermäktig\n\n"
                    "R – REDOGÖRELSE FÖR VHT\n"
                    "Genomförd: Sammanstöt med FI\n"
                    "Pågående: Svinar\n"
                    "Planerad: Gå på march\n\n"
                    "S – SLUTSATSER\nStriden är snart över\n\n"
                    "SLUT!\n"
                ),
                "groupV2": {"name": group, "id": "group123"},
            },
        }
    }


class TestForsPipelineHelpers(unittest.TestCase):
    def test_is_fors_message_true(self):
        self.assertTrue(is_fors_message("FORS-RAPPORT\nTill: A"))

    def test_is_fors_message_false(self):
        self.assertFalse(is_fors_message("7S RAPPORT\nTill: A"))

    def test_parse_fors_report_extracts_fields(self):
        fields = parse_fors_report(_make_msg_data()["envelope"]["dataMessage"]["message"])

        self.assertEqual(fields["till"], "TILL")
        self.assertEqual(fields["fran"], "FRA")
        self.assertEqual(fields["tnr"], "241330")
        self.assertEqual(fields["forbandets_position"], "UPK3")
        self.assertEqual(fields["orientering"], "FI är övermäktig")
        self.assertEqual(fields["genomford"], "Sammanstöt med FI")
        self.assertEqual(fields["pagaende"], "Svinar")
        self.assertEqual(fields["planerad"], "Gå på march")
        self.assertEqual(fields["slutsatser"], "Striden är snart över")

    def test_parse_fors_report_accepts_long_tnr_and_optional_slutsatser(self):
        text = (
            "FORS-RAPPORT\n"
            "Till: TILL\n"
            "Från: FRA\n"
            "TNR: 241330BAPR2026\n\n"
            "F FÖRBANDETS POSITION\n"
            "UPK3\n\n"
            "O ORIENTERING\n"
            "FI är övermäktig\n\n"
            "R REDOGÖRELSE FÖR VHT\n"
            "Genomförd verksamhet: Sammanstöt med FI\n"
            "Pågående verksamhet: Svinar\n"
            "Planerad verksamhet: Gå på march\n\n"
            "SLUT!\n"
        )

        fields = parse_fors_report(text)

        self.assertEqual(fields["tnr"], "241330BAPR2026")
        self.assertEqual(fields["genomford"], "Sammanstöt med FI")
        self.assertEqual(fields["pagaende"], "Svinar")
        self.assertEqual(fields["planerad"], "Gå på march")
        self.assertNotIn("slutsatser", fields)


class TestForsPipelineRun(unittest.IsolatedAsyncioTestCase):
    @patch("oden.pipelines.fors.get_app_state")
    async def test_run_handles_fors_and_writes_report_file(self, mock_get_app_state):
        app_state = Mock()
        app_state.resolve_contact_name.return_value = "Nicklas"
        mock_get_app_state.return_value = app_state

        with tempfile.TemporaryDirectory() as tmpdir, patch("oden.config.VAULT_PATH", tmpdir):
            pipeline = ForsPipeline()

            handled = await pipeline.run(
                msg_data=_make_msg_data(),
                reader=AsyncMock(),
                writer=AsyncMock(),
            )

            self.assertTrue(handled)
            output_path = Path(tmpdir) / "7s-test" / "TNR241330.md"
            self.assertTrue(output_path.exists())
            content = output_path.read_text(encoding="utf-8")

        self.assertIn("typ: FORS-rapport", content)
        self.assertIn('tnr: "241330"', content)
        self.assertIn('tidpunkt: "2026-06-24T13:30:00"', content)
        self.assertIn('signal_tidpunkt: "2026-06-24T15:31:09"', content)
        self.assertIn('signal_avsandare_nummer: "+46701234567"', content)
        self.assertIn('signal_avsandare_id: "dd1bac1d-b955-4ac0-9d53-14053c4fe69f"', content)
        self.assertIn("**Till:** TILL", content)
        self.assertIn("**Från:** FRA", content)
        self.assertIn("## F – FÖRBANDETS POSITION", content)
        self.assertIn("UPK3", content)
        self.assertIn("## O – ORIENTERING", content)
        self.assertIn("FI är övermäktig", content)
        self.assertIn("**Genomförd:** Sammanstöt med FI", content)
        self.assertIn("**Pågående:** Svinar", content)
        self.assertIn("**Planerad:** Gå på march", content)
        self.assertIn("## S – SLUTSATSER", content)
        self.assertIn("Striden är snart över", content)
        self.assertTrue(content.rstrip().endswith("SLUT!"))

    @patch("oden.pipelines.fors.get_app_state")
    async def test_run_handles_long_tnr_without_slutsatser(self, mock_get_app_state):
        app_state = Mock()
        app_state.resolve_contact_name.return_value = "Nicklas"
        mock_get_app_state.return_value = app_state

        with tempfile.TemporaryDirectory() as tmpdir, patch("oden.config.VAULT_PATH", tmpdir):
            pipeline = ForsPipeline()
            msg_data = _make_msg_data(tnr="241330BAPR2026")
            msg_data["envelope"]["dataMessage"]["message"] = msg_data["envelope"]["dataMessage"]["message"].replace(
                "S – SLUTSATSER\nStriden är snart över\n\n", ""
            )

            handled = await pipeline.run(
                msg_data=msg_data,
                reader=AsyncMock(),
                writer=AsyncMock(),
            )

            self.assertTrue(handled)
            output_path = Path(tmpdir) / "7s-test" / "TNR241330BAPR2026.md"
            self.assertTrue(output_path.exists())
            content = output_path.read_text(encoding="utf-8")

        self.assertIn('tnr: "241330BAPR2026"', content)
        self.assertIn('tidpunkt: "2026-04-24T13:30:00"', content)
        self.assertNotIn("## S – SLUTSATSER", content)

    async def test_run_skips_non_fors(self):
        pipeline = ForsPipeline()
        msg_data = {
            "envelope": {
                "sourceName": "Nicklas",
                "sourceNumber": "+46701234567",
                "timestamp": _TIMESTAMP,
                "dataMessage": {
                    "message": "Vanligt meddelande",
                    "groupV2": {"name": "test", "id": "group123"},
                },
            }
        }

        handled = await pipeline.run(
            msg_data=msg_data,
            reader=AsyncMock(),
            writer=AsyncMock(),
        )

        self.assertFalse(handled)
