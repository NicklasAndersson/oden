import unittest
from unittest.mock import AsyncMock, Mock, mock_open, patch

from oden.pipelines.seven_s import SevenSPipeline, is_7s_message, parse_7s_report


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
            "Sagesman: 2A GRUPP\n"
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
    @patch("oden.pipelines.seven_s.open", new_callable=mock_open)
    @patch("oden.pipelines.seven_s.os.makedirs")
    @patch("oden.pipelines.seven_s.get_message_filepath")
    @patch("oden.pipelines.seven_s.get_app_state")
    async def test_run_handles_7s_and_writes_file(self, mock_get_app_state, mock_get_path, mock_makedirs, mock_file):
        mock_get_path.return_value = "/tmp/vault/7s/220932-test.md"

        app_state = Mock()
        app_state.resolve_contact_name.return_value = "Nicklas"
        mock_get_app_state.return_value = app_state

        pipeline = SevenSPipeline()
        msg_data = {
            "envelope": {
                "sourceName": "Nicklas",
                "sourceNumber": "+46701234567",
                "timestamp": 1765890600000,
                "dataMessage": {
                    "message": (
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
                        "Sagesman: 2A GRUPP\n"
                        "Sedan: Fortsätter spaning\n"
                    ),
                    "groupV2": {"name": "7s-test", "id": "group123"},
                },
            }
        }

        handled = await pipeline.run(
            msg_data=msg_data,
            reader=AsyncMock(),
            writer=AsyncMock(),
        )

        self.assertTrue(handled)
        mock_makedirs.assert_called_once()
        mock_file.assert_called_once_with("/tmp/vault/7s/220932-test.md", "w", encoding="utf-8")

    @patch("oden.pipelines.seven_s.open", new_callable=mock_open)
    async def test_run_skips_non_7s(self, mock_file):
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
        mock_file.assert_not_called()
