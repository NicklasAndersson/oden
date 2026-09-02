"""ATAK 8S report -> 7S file mapping (see oden/tak/eight_s.py)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from oden.pipelines.seven_s import SevenSPipeline, parse_7s_report
from oden.pipelines.structured_report import trailing_obsidian_comment
from oden.tak.cot import cot_to_inbound
from oden.tak.eight_s import is_8s_report, to_7s_message
from oden.tak.listener import build_envelope

_FIX = Path(__file__).parent / "fixtures" / "tak"


def _cot():
    return cot_to_inbound((_FIX / "8s_report.xml").read_bytes())


class DetectTest(unittest.TestCase):
    def test_detects_8s_report(self):
        self.assertTrue(is_8s_report(_cot()))

    def test_ignores_plain_marker(self):
        self.assertFalse(is_8s_report(cot_to_inbound((_FIX / "spi_pointer.xml").read_bytes())))


class ToSevenSMessageTest(unittest.TestCase):
    def setUp(self):
        self.msg = to_7s_message(_cot())

    def test_parses_as_a_7s_report(self):
        fields = parse_7s_report(self.msg)
        self.assertEqual(fields["tnr"], "312132")
        self.assertEqual(fields["stund"], "312132ZAUG2026")
        self.assertEqual(fields["sagesman"], "LarsNo")
        self.assertEqual(fields["sedan"], "Somnar om")
        self.assertIn("34V CL 3939 8179", fields["stalle"])  # original grid kept as place text
        self.assertIn("medelålders man", fields["handelse"])

    def test_raw_8s_ridealong_is_a_hidden_comment(self):
        comment = trailing_obsidian_comment(self.msg)
        self.assertTrue(comment.startswith("%%") and comment.endswith("%%"))
        self.assertIn("Position: 34V CL 3939 8179", comment)
        self.assertIn("Then: Somnar om", comment)
        self.assertIn("lat: 59.3442335", comment)  # exact CoT point, not the MGRS round-trip


class TrailingCommentTest(unittest.TestCase):
    def test_none_when_absent(self):
        self.assertEqual(trailing_obsidian_comment("7S RAPPORT\nTill: A\n"), "")

    def test_only_trailing_block(self):
        text = "body %%inline%% more\n\n%%\nkept\n%%"
        self.assertEqual(trailing_obsidian_comment(text), "%%\nkept\n%%")


class PipelineTest(unittest.IsolatedAsyncioTestCase):
    @patch("oden.pipelines.structured_report.get_app_state")
    async def test_8s_cot_becomes_a_7s_file_with_hidden_raw_block(self, mock_get_app_state):
        app_state = Mock()
        app_state.resolve_contact_name.return_value = None
        mock_get_app_state.return_value = app_state

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("oden.config.VAULT_PATH", tmpdir),
            patch("oden.config.GROUP_SPLIT_ENABLED", False),
        ):
            handled = await SevenSPipeline().run(
                msg_data=build_envelope(_cot(), "TAK Inkommande"),
                reader=AsyncMock(),
                writer=AsyncMock(),
            )
            self.assertTrue(handled)
            content = (Path(tmpdir) / "TNR312132.md").read_text(encoding="utf-8")

        self.assertIn("typ: 7S-rapport", content)
        self.assertIn('tnr: "312132"', content)
        self.assertIn('tidpunkt: "2026-08-31T21:32:00"', content)
        self.assertIn("lat: 59.344", content)  # recovered from the MGRS in Ställe
        self.assertIn("**Händelse:** En, medelålders man", content)
        self.assertIn("**Symbol:** Rekyl T-shirt", content)
        self.assertIn("**Sedan:** Somnar om", content)
        self.assertTrue(content.rstrip().endswith("%%"))
        self.assertIn("Position: 34V CL 3939 8179", content)


if __name__ == "__main__":
    unittest.main()
