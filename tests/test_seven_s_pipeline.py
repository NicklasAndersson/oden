import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from oden import config as cfg
from oden.pipelines.seven_s import SevenSPipeline, is_7s_message, parse_7s_report

_TIMESTAMP = int(datetime.datetime(2026, 6, 22, 19, 31, 5, tzinfo=cfg.TIMEZONE).timestamp() * 1000)


def _make_msg_data(*, sagesman="AQ", stalle="Långkärrsvägen", symbol="Svart", group="7s-test"):
    return {
        "envelope": {
            "sourceName": "Nicklas",
            "sourceNumber": "+46701234567",
            "timestamp": _TIMESTAMP,
            "dataMessage": {
                "message": (
                    f"7S RAPPORT\nTill: TST\nFrån: TS\nTNR: 221520\nStund: 221520\n"
                    f"Ställe: {stalle}\nStyrka: 1\nSlag: Vi\nSysselsättning: Patrull\n"
                    f"Symbol: {symbol}\nSagesman: {sagesman}\nSedan: Återgår till bas\n"
                ),
                "groupV2": {"name": group, "id": "group123"},
            },
        }
    }


class TestSevenSPipelineHelpers(unittest.TestCase):
    def test_is_7s_message_true(self):
        self.assertTrue(is_7s_message("7S RAPPORT\nTill: A"))

    def test_is_7s_message_false(self):
        self.assertFalse(is_7s_message("Lagesrapport\nTill: A"))

    def test_parse_7s_report_extracts_fields(self):
        text = (
            "7S RAPPORT\n"
            "Till: TILL_NAMN\n"
            "Från: FRAN_NAMN\n"
            "TNR: 220932\n"
            "Stund: 220930\n"
            "Ställe: 33VXF 56007 96107\n"
            "Styrka: 2\n"
            "Slag: Personbil\n"
            "Sysselsättning: Spanar\n"
            "Symbol: Svart\n"
            "Sagesman: AQ\n"
            "Sedan: Fortsätter spaning\n"
        )

        fields = parse_7s_report(text)

        self.assertEqual(fields["till"], "TILL_NAMN")
        self.assertEqual(fields["fran"], "FRAN_NAMN")
        self.assertEqual(fields["tnr"], "220932")
        self.assertEqual(fields["stund"], "220930")
        self.assertEqual(fields["stalle"], "33VXF 56007 96107")

    def test_parse_7s_report_missing_required_raises(self):
        text = "7S RAPPORT\nTill: A\n"
        with self.assertRaises(ValueError):
            parse_7s_report(text)


class TestSevenSPipelineRun(unittest.IsolatedAsyncioTestCase):
    @patch("oden.pipelines.seven_s.get_app_state")
    @patch("oden.config.REGEX_PATTERNS", {"custom_feature": r"logotyp-fragment DGE"})
    async def test_run_handles_7s_and_writes_spec_file(self, mock_get_app_state):
        app_state = Mock()
        app_state.resolve_contact_name.return_value = "Nicklas"
        mock_get_app_state.return_value = app_state

        with tempfile.TemporaryDirectory() as tmpdir, patch("oden.config.VAULT_PATH", tmpdir):
            pipeline = SevenSPipeline()
            msg_data = _make_msg_data(
                stalle="34VCM 79349 26095, Långkärrsvägen",
                symbol="ABC123 och logotyp-fragment DGE",
            )

            handled = await pipeline.run(
                msg_data=msg_data,
                reader=AsyncMock(),
                writer=AsyncMock(),
            )

            self.assertTrue(handled)
            output_path = Path(tmpdir) / "7s-test" / "TNR221520.md"
            self.assertTrue(output_path.exists())
            content = output_path.read_text(encoding="utf-8")

        self.assertIn("typ: 7S-rapport", content)
        self.assertIn('tnr: "221520"', content)
        self.assertIn('tidpunkt: "2026-06-22T15:20:00"', content)
        self.assertIn('plats: "Långkärrsvägen"', content)
        self.assertIn("lat: 59.49063", content)
        self.assertIn("lon: 17.46740", content)
        self.assertIn('location: "59.49063,17.46740"', content)
        self.assertIn("sagesman: AQ", content)
        self.assertIn("**TNR:** 221520", content)
        self.assertIn("**Stund:** 2026-06-22 15:20", content)
        self.assertIn("**Ställe:** Långkärrsvägen", content)
        self.assertIn("**Symbol:** [[ABC123]] och [[logotyp-fragment DGE]]", content)
        self.assertNotIn("# 7S RAPPORT", content)
        self.assertNotIn("## Metadata", content)

    @patch("oden.pipelines.seven_s.get_app_state")
    async def test_run_adds_collision_suffix_to_filename_and_tnr(self, mock_get_app_state):
        app_state = Mock()
        app_state.resolve_contact_name.return_value = "Nicklas"
        mock_get_app_state.return_value = app_state

        with tempfile.TemporaryDirectory() as tmpdir, patch("oden.config.VAULT_PATH", tmpdir):
            group_dir = Path(tmpdir) / "7s-test"
            group_dir.mkdir(parents=True, exist_ok=True)
            (group_dir / "TNR221520.md").write_text("existing\n", encoding="utf-8")

            pipeline = SevenSPipeline()
            handled = await pipeline.run(
                msg_data=_make_msg_data(),
                reader=AsyncMock(),
                writer=AsyncMock(),
            )

            self.assertTrue(handled)
            output_path = group_dir / "TNR221520_2.md"
            self.assertTrue(output_path.exists())
            content = output_path.read_text(encoding="utf-8")

        self.assertIn('tnr: "221520_2"', content)
        self.assertIn("**TNR:** 221520_2", content)

    async def test_run_skips_non_7s(self):
        pipeline = SevenSPipeline()
        msg_data = {
            "envelope": {
                "sourceName": "Nicklas",
                "sourceNumber": "+46701234567",
                "timestamp": 1765890600000,
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

    @patch("oden.pipelines.seven_s.get_app_state")
    async def test_run_rejects_invalid_sagesman_for_schema(self, mock_get_app_state):
        app_state = Mock()
        app_state.resolve_contact_name.return_value = "Nicklas"
        mock_get_app_state.return_value = app_state

        with tempfile.TemporaryDirectory() as tmpdir, patch("oden.config.VAULT_PATH", tmpdir):
            pipeline = SevenSPipeline()
            with self.assertRaisesRegex(ValueError, "Sagesman"):
                await pipeline.run(
                    msg_data=_make_msg_data(sagesman="2A GRUPP"),
                    reader=AsyncMock(),
                    writer=AsyncMock(),
                )
