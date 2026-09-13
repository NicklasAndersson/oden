import asyncio
import json
import shutil
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from oden.config_db import init_db
from oden.messages_db import STATUS_PROCESSED, create_raw_message, get_message_detail
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.pipelines.seven_s import is_7s_message
from oden.tak.cot import cot_to_inbound
from oden.tak.listener import (
    _SEEN_CAP,
    _SEEN_MAX_AGE_S,
    _TALLY_CAP,
    INBOUND_GROUP_ID,
    OBSERVATION_HEADER,
    InboundFilter,
    _count,
    _describe_tally,
    _Seen,
    build_envelope,
    load_seen,
    render_observation,
    run_tak_listener,
    save_seen,
)


def _cot(
    uid="ENEMY.1", cot_type="a-h-G", lat=59.33, lon=18.07, callsign="Alpha", remarks="Två fordon", custom_report=""
):
    xml = (
        f"<event version='2.0' uid='{uid}' type='{cot_type}' how='m-g' "
        f"time='2026-08-28T14:30:00.00Z'>"
        f"<point lat='{lat}' lon='{lon}' hae='9999999.0' ce='9999999.0' le='9999999.0'/>"
        f"<detail><contact callsign='{callsign}'/><remarks>{remarks}</remarks>{custom_report}</detail></event>"
    )
    return cot_to_inbound(xml)


class InboundFilterTest(unittest.TestCase):
    def _filter(self, **overrides):
        return InboundFilter({"inbound_types": ["a-h-*", "a-u-*"], **overrides})

    def test_accepts_hostile(self):
        self.assertTrue(self._filter().accept(_cot()))

    def test_rejects_friendly_pli_by_default(self):
        self.assertFalse(self._filter().accept(_cot(cot_type="a-f-G-U-C")))

    def test_default_types_accept_manual_markers_and_points(self):
        # No inbound_types override -> the shipped defaults.
        f = InboundFilter({})
        self.assertTrue(f.accept(_cot(uid="m1", cot_type="a-f-G")))  # manually placed friendly marker
        self.assertTrue(f.accept(_cot(uid="m2", cot_type="a-u-G")))
        self.assertTrue(f.accept(_cot(uid="m3", cot_type="b-m-p-s-m")))  # dropped point
        self.assertFalse(f.accept(_cot(uid="p1", cot_type="a-f-G-U-C")))  # friendly PLI still filtered

    def test_reject_reason_is_recorded(self):
        f = self._filter()
        f.accept(_cot(cot_type="b-m-p-w"))
        self.assertIn("inbound_types", f.last_reject)
        f.accept(_cot(uid="ODEN.x"))
        self.assertIn("eko", f.last_reject)

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

    def test_dedup_lets_through_changed_custom_report(self):
        f = self._filter()
        report_a = "<custom_report><line1_size>3x Personnel</line1_size></custom_report>"
        report_b = "<custom_report><line1_size>5x Personnel</line1_size></custom_report>"
        self.assertTrue(f.accept(_cot(custom_report=report_a)))
        self.assertTrue(f.accept(_cot(custom_report=report_b)))
        self.assertFalse(f.accept(_cot(custom_report=report_b)))  # now unchanged

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

    def test_observation_renders_custom_report_fields(self):
        report = (
            "<custom_report name='8-Line Spot Report'>"
            "<line1_size>3x Personnel</line1_size>"
            "<line3_location>11S YT 1234 5678</line3_location>"
            "</custom_report>"
        )
        text = render_observation(_cot(custom_report=report))
        self.assertIn("8-Line Spot Report", text)
        self.assertIn("line1_size: 3x Personnel", text)
        self.assertIn("line3_location: 11S YT 1234 5678", text)

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


_FIX = Path(__file__).parent / "fixtures" / "tak"
_DEFAULT_TYPES = ["a-f-G", "a-h-*", "a-n-G", "a-u-*", "b-m-p-*", "b-a-*"]


def _raw(uid="ENEMY.1", cot_type="a-h-G", lat=59.33, lon=18.07):
    """The same shape as _cot(), but left as raw bytes off the wire."""
    return (
        f"<event version='2.0' uid='{uid}' type='{cot_type}' how='m-g' time='2026-08-28T14:30:00.00Z'>"
        f"<point lat='{lat}' lon='{lon}' hae='9999999.0' ce='9999999.0' le='9999999.0'/>"
        f"<detail><contact callsign='Alpha'/><remarks>Två fordon</remarks></detail></event>"
    ).encode()


class PrescreenTest(unittest.TestCase):
    """The pre-screen may say "certainly reject" or "don't know" — never more."""

    def _filter(self, **overrides):
        return InboundFilter({"inbound_types": _DEFAULT_TYPES, **overrides})

    def test_rejects_the_friendly_pli_flood_without_parsing(self):
        self.assertTrue(self._filter().prescreen_rejects(_raw(cot_type="a-f-G-U-C")))

    def test_lets_a_whitelisted_type_through_to_the_full_parse(self):
        self.assertFalse(self._filter().prescreen_rejects(_raw(cot_type="a-h-G")))

    def test_never_rejects_what_accept_would_take(self):
        """The invariant the optimization rests on, over real and awkward payloads."""
        payloads = [path.read_bytes() for path in sorted(_FIX.glob("*.xml"))]
        payloads += [
            _raw(cot_type=t) for t in ("a-h-G", "a-f-G", "a-f-G-U-C", "b-m-p-s-p-i", "b-a-o-tbl", "t-x-takp-v")
        ]
        payloads += [
            b"<event uid='x' type='a-h-G'><detail><link type='a-f-G-U-C'/></detail></event>",
            b'<!-- <event type="a-f-G-U-C"/> --><event uid="x" type="a-h-G"><point lat="59.3" lon="18.0"/></event>',
            b'<event uid="x" type="a-f&#45;G"><point lat="59.3" lon="18.0"/></event>',
            b"\xbf\x01\xbf\x12takproto",
            b"inte xml alls",
            b"",
        ]
        for data in payloads:
            with self.subTest(data=data[:60]):
                cot = cot_to_inbound(data)
                would_accept = cot is not None and InboundFilter({"inbound_types": _DEFAULT_TYPES}).accept(cot)
                if would_accept:
                    self.assertFalse(
                        self._filter().prescreen_rejects(data),
                        "förfiltret kastade något som filtret hade släppt igenom",
                    )

    def test_leaves_filter_state_untouched(self):
        filt = self._filter()
        for _ in range(100):
            self.assertTrue(filt.prescreen_rejects(_raw(cot_type="a-f-G-U-C")))
        self.assertEqual(filt._seen, {})
        self.assertEqual(filt._window_count, 0)

    def test_disabled_when_no_types_are_configured(self):
        self.assertFalse(InboundFilter({"inbound_types": []}).prescreen_rejects(_raw(cot_type="a-f-G-U-C")))

    def test_undecidable_payloads_fall_through(self):
        for data in (object(), None, "<event uid='x' type='a-f-G-U-C'/>", b"\xbf\x01takproto"):
            with self.subTest(data=data):
                self.assertFalse(self._filter().prescreen_rejects(data))


class _StubBridge:
    """Just enough bridge for run_tak_listener: settings, an rx queue, counters."""

    def __init__(self, settings):
        self.settings = settings
        self.rx_queue: asyncio.Queue = asyncio.Queue()
        self.rx_total = 0
        self.rx_filtered = 0
        self.received_count = 0
        self.last_rx_at = None


class ListenerCountersTest(unittest.IsolatedAsyncioTestCase):
    """The pre-screen must not change rx_total or rx_filtered for the same traffic."""

    _TRAFFIC = None

    @classmethod
    def setUpClass(cls):
        cls._TRAFFIC = [
            _raw(cot_type="a-f-G-U-C"),  # PLI flood, pre-screened away
            _raw(cot_type="a-f-G-U-C"),
            _raw(uid="ENEMY.2", cot_type="a-h-G"),  # a note
            (_FIX / "8s_report.xml").read_bytes(),  # a note
            (_FIX / "takproto_v.xml").read_bytes(),  # server hello, no position
            b"inte xml alls",
            b"",
        ]

    async def _drain(self, *, prescreen: bool) -> tuple[int, int, int]:
        bridge = _StubBridge({"inbound_enabled": True, "inbound_types": _DEFAULT_TYPES})
        for item in self._TRAFFIC:
            bridge.rx_queue.put_nowait(item)

        created = []

        async def fake_run_message(**kwargs):
            created.append(kwargs.get("message_id"))

        with ExitStack() as stack:
            stack.enter_context(
                patch("oden.messages_db.create_raw_message", side_effect=lambda *a, **k: len(created) + 1)
            )
            stack.enter_context(patch("oden.messages_db.update_message_status"))
            stack.enter_context(
                patch(
                    "oden.pipeline_orchestrator.PipelineOrchestrator",
                    return_value=SimpleNamespace(run_message=fake_run_message),
                )
            )
            # This test is about counters, not persistence: keep the dedup cache out of
            # it, or the first run's saved state dedupes the second run's traffic.
            stack.enter_context(patch("oden.tak.listener.load_seen", return_value={}))
            stack.enter_context(patch("oden.tak.listener.save_seen"))
            if not prescreen:  # the old behaviour: parse everything, then filter
                stack.enter_context(patch.object(InboundFilter, "prescreen_rejects", lambda self, data: False))

            task = asyncio.create_task(run_tak_listener(bridge))
            while bridge.rx_queue.qsize() and not task.done():
                await asyncio.sleep(0)
            for _ in range(50):
                await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        return bridge.rx_total, bridge.rx_filtered, bridge.received_count

    async def test_counters_are_identical_with_and_without_the_prescreen(self):
        with_pre = await self._drain(prescreen=True)
        without_pre = await self._drain(prescreen=False)
        self.assertEqual(with_pre, without_pre)
        self.assertEqual(with_pre[0], len(self._TRAFFIC))
        self.assertEqual(sum(with_pre[1:]), len(self._TRAFFIC))


class TallyTest(unittest.TestCase):
    """A whitelist that never matches must say what it threw away."""

    def test_names_the_most_common_types_worst_first(self):
        tally = {"t-x-c-t": 20, "t-x-takp-v": 2, "a-f-G-U-C": 9}
        text = _describe_tally(tally)
        self.assertIn("t-x-c-t x20", text)
        self.assertLess(text.index("t-x-c-t"), text.index("a-f-G-U-C"), "vanligaste typen ska stå först")
        self.assertLess(text.index("a-f-G-U-C"), text.index("t-x-takp-v"))

    def test_says_nothing_when_nothing_was_discarded(self):
        self.assertEqual(_describe_tally({}), "")

    def test_marks_that_more_types_were_seen_than_listed(self):
        self.assertIn("m.fl.", _describe_tally({f"t-{i}": i for i in range(10)}))
        self.assertNotIn("m.fl.", _describe_tally({"t-x-c-t": 1}))

    def test_cannot_grow_without_bound(self):
        tally: dict[str, int] = {}
        for i in range(_TALLY_CAP * 3):
            _count(tally, f"typ-{i}")
        self.assertEqual(len(tally), _TALLY_CAP)

    def test_keeps_counting_types_it_already_knows_when_full(self):
        tally = {f"typ-{i}": 1 for i in range(_TALLY_CAP)}
        _count(tally, "typ-0")
        _count(tally, "en-ny-typ")
        self.assertEqual(tally["typ-0"], 2)
        self.assertNotIn("en-ny-typ", tally)


class DiscardLoggingTest(unittest.IsolatedAsyncioTestCase):
    """At DEBUG the log must name the type of every discarded event."""

    async def test_the_type_is_named_even_without_a_usable_position(self):
        bridge = _StubBridge({"inbound_enabled": True, "inbound_types": _DEFAULT_TYPES})
        # A whitelisted type that carries no position: it survives the pre-screen,
        # then the parse rejects it — the case where the type used to go unsaid.
        bridge.rx_queue.put_nowait(_raw(cot_type="a-h-G", lat=0.0, lon=0.0))
        bridge.rx_queue.put_nowait(_raw(cot_type="a-f-G-U-C"))  # the flood, pre-screened away

        with self.assertLogs("oden.tak.listener", level="DEBUG") as logs:
            task = asyncio.create_task(run_tak_listener(bridge))
            for _ in range(50):
                await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        lines = "\n".join(logs.output)
        self.assertIn("typ=a-h-G — ingen användbar position", lines)
        self.assertIn("typ=a-f-G-U-C", lines)
        self.assertIn("utanför inbound_types", lines)

    async def test_the_summary_names_what_was_discarded(self):
        bridge = _StubBridge({"inbound_enabled": True, "inbound_types": _DEFAULT_TYPES})
        for _ in range(3):
            bridge.rx_queue.put_nowait(_raw(cot_type="a-f-G-U-C"))

        with (
            patch("oden.tak.listener._SUMMARY_EVERY_SECONDS", 0.0),
            self.assertLogs("oden.tak.listener", level="INFO") as logs,
        ):
            task = asyncio.create_task(run_tak_listener(bridge))
            for _ in range(50):
                await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        summaries = [line for line in logs.output if "hittills" in line]
        self.assertTrue(summaries, "ingen sammanfattningsrad loggades")
        self.assertIn("bortfiltrerade typer: a-f-G-U-C", summaries[-1])


class SeenPersistenceTest(unittest.TestCase):
    """The dedup cache must survive a restart, or every restart re-imports the picture."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "tak" / "inbound-seen.json"

    def _filter(self, **kw):
        return InboundFilter({"inbound_types": _DEFAULT_TYPES}, **kw)

    def test_a_marker_imported_before_a_restart_is_not_imported_again(self):
        before = self._filter()
        cot = _cot(uid="8S.abc", cot_type="a-h-G")
        self.assertTrue(before.accept(cot), "första gången ska den släppas igenom")
        save_seen(before.seen_snapshot(), self.path)

        after = self._filter(seen=load_seen(self.path))
        self.assertFalse(after.accept(_cot(uid="8S.abc", cot_type="a-h-G")))
        self.assertIn("dedup", after.last_reject)

    def test_real_movement_still_gets_through_after_a_restart(self):
        before = self._filter()
        before.accept(_cot(uid="8S.abc", cot_type="a-h-G", lat=59.33, lon=18.07))
        save_seen(before.seen_snapshot(), self.path)

        after = self._filter(seen=load_seen(self.path))
        self.assertTrue(after.accept(_cot(uid="8S.abc", cot_type="a-h-G", lat=59.40, lon=18.07)))

    def test_nothing_saved_means_nothing_remembered(self):
        self.assertEqual(load_seen(self.path), {})

    def test_a_corrupt_file_costs_a_reimport_not_a_crash(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{detta är inte json", encoding="utf-8")
        with self.assertLogs("oden.tak.listener", level="WARNING"):
            self.assertEqual(load_seen(self.path), {})

    def test_a_single_bad_row_does_not_cost_the_good_ones(self):
        self.path.parent.mkdir(parents=True)
        now = time.time()
        self.path.write_text(
            json.dumps(
                {
                    "seen": {
                        "bra": {"lat": 59.3, "lon": 18.0, "signature": "x", "cot_type": "a-h-G", "seen_at": now},
                        "trasig": {"lat": "inte ett tal", "cot_type": "a-h-G"},
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(list(load_seen(self.path)), ["bra"])

    def test_entries_it_has_not_seen_for_a_month_are_forgotten(self):
        now = time.time()
        stale = {"gammal": _Seen(59.3, 18.0, "x", "a-h-G", seen_at=now - _SEEN_MAX_AGE_S - 60)}
        fresh = {"ny": _Seen(59.3, 18.0, "x", "a-h-G", seen_at=now)}
        save_seen({**stale, **fresh}, self.path)
        self.assertEqual(list(load_seen(self.path, now=now)), ["ny"])

    def test_an_oversized_file_keeps_the_most_recent(self):
        now = time.time()
        crowd = {f"uid-{i}": _Seen(59.3, 18.0, "x", "a-h-G", seen_at=now - i) for i in range(_SEEN_CAP + 50)}
        save_seen(crowd, self.path)
        loaded = load_seen(self.path, now=now)
        self.assertEqual(len(loaded), _SEEN_CAP)
        self.assertIn("uid-0", loaded)  # newest
        self.assertNotIn(f"uid-{_SEEN_CAP + 49}", loaded)  # oldest

    def test_the_file_is_owner_only_and_leaves_no_temp_behind(self):
        save_seen({"x": _Seen(59.3, 18.0, "s", "a-h-G", seen_at=time.time())}, self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_an_unwritable_target_is_a_warning_not_a_crash(self):
        blocker = Path(self._tmp.name) / "inte-en-katalog"
        blocker.write_text("x", encoding="utf-8")
        with self.assertLogs("oden.tak.listener", level="WARNING"):
            save_seen({"x": _Seen(59.3, 18.0, "s", "a-h-G")}, blocker / "inbound-seen.json")

    def test_the_filter_reports_whether_there_is_anything_to_save(self):
        filt = self._filter()
        self.assertFalse(filt.seen_dirty, "ett nytt filter har inget att spara")
        filt.accept(_cot(uid="8S.abc", cot_type="a-h-G"))
        self.assertTrue(filt.seen_dirty)

    def test_a_rejected_type_leaves_nothing_to_save(self):
        filt = self._filter()
        self.assertFalse(filt.accept(_cot(cot_type="a-f-G-U-C")))
        self.assertFalse(filt.seen_dirty, "en kastad CoT ska inte orsaka en skrivning")


class RestartDoesNotDuplicateTest(unittest.IsolatedAsyncioTestCase):
    """The bug itself: a restart used to re-import every live marker as a new note."""

    async def _run_once(self, seen_path: Path) -> int:
        """Start a listener, feed the same live marker, stop it. Returns notes created."""
        bridge = _StubBridge({"inbound_enabled": True, "inbound_types": _DEFAULT_TYPES})
        bridge.rx_queue.put_nowait(_raw(uid="8S.live", cot_type="a-h-G"))

        with ExitStack() as stack:
            stack.enter_context(patch("oden.tak.listener._seen_path", return_value=seen_path))
            stack.enter_context(patch("oden.messages_db.create_raw_message", side_effect=lambda *a, **k: 1))
            stack.enter_context(patch("oden.messages_db.update_message_status"))

            async def noop(**kwargs):
                return None

            stack.enter_context(
                patch(
                    "oden.pipeline_orchestrator.PipelineOrchestrator",
                    return_value=SimpleNamespace(run_message=noop),
                )
            )
            task = asyncio.create_task(run_tak_listener(bridge))
            for _ in range(50):
                await asyncio.sleep(0)
            task.cancel()  # a clean stop, which is when the cache is written
            with self.assertRaises(asyncio.CancelledError):
                await task
        return bridge.received_count

    async def test_the_same_live_marker_is_not_imported_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen_path = Path(tmp) / "tak" / "inbound-seen.json"

            first = await self._run_once(seen_path)
            self.assertEqual(first, 1, "första körningen ska skapa noten")
            self.assertTrue(seen_path.is_file(), "dedup-cachen skrevs inte vid nedstängning")

            second = await self._run_once(seen_path)
            self.assertEqual(second, 0, "omstarten importerade markören igen")

    async def test_without_the_saved_cache_it_would_import_again(self):
        """Guards the test above: prove the second run only passes because of the file."""
        with tempfile.TemporaryDirectory() as tmp:
            await self._run_once(Path(tmp) / "tak" / "seen-a.json")
            again = await self._run_once(Path(tmp) / "tak" / "seen-b.json")
            self.assertEqual(again, 1)


if __name__ == "__main__":
    unittest.main()
