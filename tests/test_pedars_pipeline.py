import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from oden import config as cfg
from oden.pipelines.pedars import PedarsPipeline, is_pedars_message, parse_pedars_report

_TIMESTAMP = int(datetime.datetime(2026, 6, 24, 15, 45, 5, tzinfo=cfg.TIMEZONE).timestamp() * 1000)
_SERVER_RECEIVED_TIMESTAMP = int(datetime.datetime(2026, 6, 24, 15, 45, 9, tzinfo=cfg.TIMEZONE).timestamp() * 1000)


def _make_msg_data(*, group="7s-test", tnr="241345"):
    return {
        "envelope": {
            "sourceName": "Nicklas",
            "sourceNumber": "+46701234567",
            "sourceUuid": "dd1bac1d-b955-4ac0-9d53-14053c4fe69f",
            "timestamp": _TIMESTAMP,
            "serverReceivedTimestamp": _SERVER_RECEIVED_TIMESTAMP,
            "dataMessage": {
                "message": (
                    "PEDARS – UNDERHÅLLSRAPPORT\n"
                    "Till: -\n"
                    "Från: -\n\n"
                    f"TNR: {tnr}\n\n"
                    "P – PERSONAL\n"
                    "Ska vara: 36  |  I tjänst: 35\n"
                    "Avvikelser:\n"
                    "- Andersson (Permission)\n\n"
                    "E – ERSÄTTNING AV FÖRNÖDENHETER\n"
                    "10L Vatten\n\n"
                    "D – DRIVMEDEL\n"
                    "Fordon:\n"
                    "PB8 (123456): 50%\n"
                    "Ved/Kaminer:\n"
                    "Kamin: 2 knippen\n\n"
                    "A – AMMUNITION\n"
                    "7.62: kvar: 50%, behov: 2000\n"
                    "9 mm: kvar: 100%\n\n"
                    "R – REPARATIONER\n"
                    "PB8 (234567): — | Körbar: Ja\n\n"
                    "S – SAMLAD FÖRMÅGA\n"
                    "GRÖN – Fullt stridsduglig\n"
                    "Allt gott\n\n"
                    "SLUT!\n"
                ),
                "groupV2": {"name": group, "id": "group123"},
            },
        }
    }


class TestPedarsPipelineHelpers(unittest.TestCase):
    def test_is_pedars_message_true(self):
        self.assertTrue(is_pedars_message("PEDARS – UNDERHÅLLSRAPPORT\nTill: A"))

    def test_is_pedars_message_false(self):
        self.assertFalse(is_pedars_message("FORS-RAPPORT\nTill: A"))

    def test_parse_pedars_report_extracts_sections(self):
        fields = parse_pedars_report(_make_msg_data()["envelope"]["dataMessage"]["message"])

        self.assertEqual(fields["tnr"], "241345")
        self.assertEqual(fields["personal"]["counts"]["ska_vara"], "36")
        self.assertEqual(fields["personal"]["counts"]["i_tjanst"], "35")
        self.assertEqual(fields["personal"]["avvikelser"], ["Andersson (Permission)"])
        self.assertEqual(fields["ersattning"], "10L Vatten")
        self.assertEqual(fields["drivmedel"]["fordon"], ["PB8 (123456): 50%"])
        self.assertEqual(fields["drivmedel"]["ved_kaminer"], ["Kamin: 2 knippen"])
        self.assertEqual(fields["ammunition"], ["7.62: kvar: 50%, behov: 2000", "9 mm: kvar: 100%"])
        self.assertEqual(fields["reparationer"], ["PB8 (234567): — | Körbar: Ja"])
        self.assertEqual(fields["samlad_formaga"]["status"], "Grön")
        self.assertEqual(fields["samlad_formaga"]["notes"], "Allt gott")

    def test_parse_pedars_report_accepts_long_tnr_and_all_drivmedel_categories(self):
        text = (
            "PEDARS - UNDERHÅLLSRAPPORT\n"
            "Till: TILL\n"
            "Från: FRA\n"
            "TNR: 241345BAPR2026\n\n"
            "P PERSONAL\n"
            "Totalt: 36 | I tjänst: 35 | Ska vara: 36\n\n"
            "E ERSÄTTNING AV FÖRNÖDENHETER\n"
            "Batterier\n\n"
            "D DRIVMEDEL\n"
            "Fordon:\n"
            "PB8: 50%\n"
            "Elverk:\n"
            "Elverk 1: 30%\n"
            "Lampor / Belysning:\n"
            "IR-lampa: 80%\n"
            "Ved / Kaminer:\n"
            "Ved: 4 säckar\n\n"
            "A AMMUNITION\n"
            "7.62: kvar: 50%, behov: 2000\n\n"
            "R REPARATIONER\n"
            "PB8: service\n\n"
            "S SAMLAD FÖRMÅGA\n"
            "Gul – Reducerad förmåga\n"
            "Reservkraft låg\n\n"
            "SLUT!\n"
        )

        fields = parse_pedars_report(text)

        self.assertEqual(fields["tnr"], "241345BAPR2026")
        self.assertEqual(fields["drivmedel"]["elverk"], ["Elverk 1: 30%"])
        self.assertEqual(fields["drivmedel"]["lampor_belysning"], ["IR-lampa: 80%"])
        self.assertEqual(fields["samlad_formaga"]["status"], "Gul")


class TestPedarsPipelineRun(unittest.IsolatedAsyncioTestCase):
    @patch("oden.pipelines.pedars.get_app_state")
    async def test_run_handles_pedars_and_writes_report_file(self, mock_get_app_state):
        app_state = Mock()
        app_state.resolve_contact_name.return_value = "Nicklas"
        mock_get_app_state.return_value = app_state

        with tempfile.TemporaryDirectory() as tmpdir, patch("oden.config.VAULT_PATH", tmpdir):
            pipeline = PedarsPipeline()

            handled = await pipeline.run(
                msg_data=_make_msg_data(),
                reader=AsyncMock(),
                writer=AsyncMock(),
            )

            self.assertTrue(handled)
            output_path = Path(tmpdir) / "TNR241345.md"
            self.assertTrue(output_path.exists())
            content = output_path.read_text(encoding="utf-8")

        self.assertIn("typ: PEDARS-rapport", content)
        self.assertIn('samlad_formaga: "Grön"', content)
        self.assertIn("## P – PERSONAL", content)
        self.assertIn("**Ska vara:** 36", content)
        self.assertIn("**I tjänst:** 35", content)
        self.assertIn("- Andersson (Permission)", content)
        self.assertIn("### Fordon", content)
        self.assertIn("- PB8 (123456): 50%", content)
        self.assertIn("### Ved / Kaminer", content)
        self.assertIn("- 7.62: kvar: 50%, behov: 2000", content)
        self.assertIn("GRÖN – Fullt stridsduglig", content)
        self.assertTrue(content.rstrip().endswith("SLUT!"))

    async def test_run_skips_non_pedars(self):
        pipeline = PedarsPipeline()
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
