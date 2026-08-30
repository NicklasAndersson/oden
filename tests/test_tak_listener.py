import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oden.config_db import init_db
from oden.messages_db import STATUS_PROCESSED, create_raw_message, get_message_detail
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.pipelines.seven_s import is_7s_message
from oden.tak.cot import cot_to_inbound
from oden.tak.listener import (
    INBOUND_GROUP_ID,
    OBSERVATION_HEADER,
    InboundFilter,
    build_envelope,
    render_observation,
)


def _cot(uid="ENEMY.1", cot_type="a-h-G", lat=59.33, lon=18.07, callsign="Alpha", remarks="Två fordon"):
    xml = (
        f"<event version='2.0' uid='{uid}' type='{cot_type}' how='m-g' "
        f"time='2026-08-28T14:30:00.00Z'>"
        f"<point lat='{lat}' lon='{lon}' hae='9999999.0' ce='9999999.0' le='9999999.0'/>"
        f"<detail><contact callsign='{callsign}'/><remarks>{remarks}</remarks></detail></event>"
    )
    return cot_to_inbound(xml)


class InboundFilterTest(unittest.TestCase):
    def _filter(self, **overrides):
        return InboundFilter({"inbound_types": ["a-h-*", "a-u-*"], **overrides})

    def test_accepts_hostile(self):
        self.assertTrue(self._filter().accept(_cot()))

    def test_rejects_friendly_pli_by_default(self):
        self.assertFalse(self._filter().accept(_cot(cot_type="a-f-G-U-C")))

    def test_rejects_own_echo(self):
        self.assertFalse(self._filter().accept(_cot(uid="ODEN.7S.281430")))

    def test_deny_list_wins(self):
        f = self._filter(inbound_callsign_deny=["alpha"])
        self.assertFalse(f.accept(_cot(callsign="Alpha")))

    def test_allow_list_excludes_others(self):
        f = self._filter(inbound_callsign_allow=["bravo"])
        self.assertFalse(f.accept(_cot(callsign="Alpha")))
        self.assertTrue(f.accept(_cot(uid="B.1", callsign="Bravo")))

    def test_dedup_suppresses_identical_repeat(self):
        f = self._filter()
        self.assertTrue(f.accept(_cot()))
        self.assertFalse(f.accept(_cot()))

    def test_dedup_lets_through_real_movement(self):
        f = self._filter(inbound_min_move_m=100)
        self.assertTrue(f.accept(_cot()))
        self.assertFalse(f.accept(_cot(lat=59.3301)))  # ~11 m
        self.assertTrue(f.accept(_cot(lat=59.34)))  # ~780 m

    def test_dedup_lets_through_changed_remarks(self):
        f = self._filter()
        self.assertTrue(f.accept(_cot()))
        self.assertTrue(f.accept(_cot(remarks="Nu tre fordon")))

    def test_rate_limit_caps_burst(self):
        f = self._filter(inbound_max_per_minute=3, inbound_min_move_m=0)
        accepted = sum(f.accept(_cot(uid=f"U{i}"), now=1000.0) for i in range(10))
        self.assertEqual(accepted, 3)

    def test_rate_limit_window_resets(self):
        f = self._filter(inbound_max_per_minute=2, inbound_min_move_m=0)
        self.assertEqual(sum(f.accept(_cot(uid=f"A{i}"), now=1000.0) for i in range(5)), 2)
        self.assertEqual(sum(f.accept(_cot(uid=f"B{i}"), now=1100.0) for i in range(5)), 2)

    def test_rate_limited_item_keeps_dedup_state(self):
        f = self._filter(inbound_max_per_minute=1, inbound_min_move_m=100)
        self.assertTrue(f.accept(_cot(uid="X"), now=1.0))  # uses the one slot
        self.assertFalse(f.accept(_cot(uid="Y"), now=1.0))  # rate-limited, but recorded
        # next window: Y unchanged -> dedup drops it, not treated as new
        self.assertFalse(f.accept(_cot(uid="Y"), now=100.0))

    def test_seen_cache_is_bounded(self):
        from oden.tak.listener import _SEEN_CAP

        f = self._filter(inbound_min_move_m=0)
        for i in range(_SEEN_CAP + 50):
            f.accept(_cot(uid=f"U{i}"), now=1.0)
        self.assertLessEqual(len(f._seen), _SEEN_CAP)

    def test_bad_numeric_settings_fall_back_to_defaults(self):
        f = InboundFilter({"inbound_min_move_m": "abc", "inbound_max_per_minute": ""})
        self.assertEqual(f.min_move_m, 100.0)
        self.assertEqual(f.max_per_minute, 60)


class RenderAndEnvelopeTest(unittest.TestCase):
    def test_observation_does_not_reparse_as_7s(self):
        # The echo guard depends on this: an inbound note must never look like a report.
        text = render_observation(_cot(remarks="7S RAPPORT\nTill: X"))
        self.assertTrue(text.startswith(OBSERVATION_HEADER))
        self.assertFalse(is_7s_message(text))

    def test_observation_contains_position_and_source(self):
        text = render_observation(_cot())
        self.assertIn("Alpha", text)
        self.assertIn("59.33000", text)
        self.assertIn("a-h-G", text)

    def test_envelope_is_signal_shaped_and_marked(self):
        env = build_envelope(_cot(), "TAK Inkommande")["envelope"]
        self.assertEqual(env["_source"], "tak")
        self.assertEqual(env["sourceNumber"], "tak:ENEMY.1")
        self.assertEqual(env["dataMessage"]["groupV2"]["id"], INBOUND_GROUP_ID)
        self.assertEqual(env["dataMessage"]["groupV2"]["name"], "TAK Inkommande")
        self.assertEqual(env["dataMessage"]["attachments"], [])
        self.assertIsInstance(env["timestamp"], int)

    def test_envelope_source_is_sanitized(self):
        cot = _cot(uid="../../etc/passwd", callsign="bad/../name")
        env = build_envelope(cot, "g")["envelope"]
        for field in (env["sourceNumber"], env["sourceName"], env["sourceUuid"]):
            self.assertNotIn("..", field)
            self.assertNotIn("/", field)


class InboundRoundTripTest(unittest.IsolatedAsyncioTestCase):
    """An inbound CoT must land as a note without being pushed back to TAK."""

    def setUp(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            self.db_path = Path(tmp.name)
        self.db_path.unlink(missing_ok=True)
        init_db(self.db_path)
        self.vault = tempfile.mkdtemp()

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)
        shutil.rmtree(self.vault, ignore_errors=True)

    async def test_inbound_cot_is_stored_and_not_republished(self):
        published: list[bytes] = []

        class Bridge:
            is_running = True
            stale_seconds = 3600
            archive = True

            async def publish(self, cot):
                published.append(cot)
                return True

        msg_data = build_envelope(_cot(), "TAK Inkommande")
        with (
            patch("oden.pipelines.tak_publish.get_tak_bridge", return_value=Bridge()),
            patch("oden.pipeline_orchestrator.get_tak_bridge", return_value=Bridge()),
            patch("oden.config.VAULT_PATH", self.vault),
            patch("oden.pipeline_orchestrator.cfg.ENABLED_PIPELINES", ["seven_s"]),
        ):
            message_id = create_raw_message(self.db_path, "+46700000000", msg_data)
            orchestrator = PipelineOrchestrator(self.db_path)
            await orchestrator.run_message(message_id=message_id, msg_data=msg_data, reader=None, writer=None)

        self.assertEqual(published, [])  # echo guard held
        self.assertEqual(get_message_detail(self.db_path, message_id)["status"], STATUS_PROCESSED)
        notes = list(Path(self.vault).rglob("*.md"))
        self.assertTrue(notes, "inkommande CoT skrev ingen not i valvet")
        self.assertIn(OBSERVATION_HEADER, notes[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
