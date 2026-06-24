import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oden.config_db import init_db
from oden.messages_db import STATUS_FAILED, STATUS_PROCESSED, create_raw_message, get_message_detail
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.pipelines_db import get_events_for_run, get_runs_for_message


class _FailingPipeline:
    name = "failing"

    async def run(self, *, msg_data, reader, writer):
        del msg_data, reader, writer
        raise RuntimeError("boom")


class _HandlingPipeline:
    name = "handling"

    async def run(self, *, msg_data, reader, writer):
        del msg_data, reader, writer
        return True


class _WarningPipeline:
    name = "warning"

    async def run(self, *, msg_data, reader, writer):
        del msg_data, reader, writer
        self.last_warnings = [{"message": "non-canonical sagesman", "field": "sagesman", "value": "2A GRUPP"}]
        return True


class TestPipelineOrchestrator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            self.db_path = Path(tmp.name)
        self.db_path.unlink(missing_ok=True)
        init_db(self.db_path)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def _create_sample_message(self) -> int:
        msg_data = {
            "envelope": {
                "sourceNumber": "+46701111111",
                "sourceName": "Test",
                "timestamp": 1710000000000,
                "dataMessage": {
                    "message": "hej",
                    "groupV2": {"id": "grp-1", "name": "Test Group"},
                },
            }
        }
        return create_raw_message(self.db_path, "+46700000000", msg_data)

    async def test_run_message_crash_marks_failed_but_keeps_raw_payload(self):
        message_id = self._create_sample_message()
        orchestrator = PipelineOrchestrator(self.db_path)
        orchestrator._build_pipelines = lambda: [_FailingPipeline()]  # type: ignore[method-assign]

        with self.assertRaises(RuntimeError):
            await orchestrator.run_message(
                message_id=message_id,
                msg_data={"envelope": {"dataMessage": {"message": "hej"}}},
                reader=None,
                writer=None,
            )

        detail = get_message_detail(self.db_path, message_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["status"], STATUS_FAILED)
        self.assertIsInstance(detail["envelope_raw"], dict)

        runs = get_runs_for_message(self.db_path, message_id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("boom", runs[0]["error_message"] or "")

        events = get_events_for_run(self.db_path, runs[0]["id"])
        event_types = [event["event_type"] for event in events]
        self.assertIn("pipeline_started", event_types)
        self.assertIn("pipeline_failed", event_types)

    async def test_reprocess_twice_keeps_single_raw_message(self):
        message_id = self._create_sample_message()
        orchestrator = PipelineOrchestrator(self.db_path)
        orchestrator._build_pipelines = lambda: [_HandlingPipeline()]  # type: ignore[method-assign]

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM raw_messages")
            before_count = cursor.fetchone()[0]
        finally:
            conn.close()

        first = await orchestrator.reprocess(message_id=message_id, reader=None, writer=None)
        second = await orchestrator.reprocess(message_id=message_id, reader=None, writer=None)

        self.assertTrue(first)
        self.assertTrue(second)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM raw_messages")
            after_count = cursor.fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(before_count, 1)
        self.assertEqual(after_count, 1)

        runs = get_runs_for_message(self.db_path, message_id)
        self.assertEqual(len(runs), 2)
        self.assertTrue(all(run["status"] == "done" for run in runs))

        detail = get_message_detail(self.db_path, message_id)
        self.assertEqual(detail["status"], STATUS_PROCESSED)

    async def test_reprocess_returns_false_for_missing_message(self):
        orchestrator = PipelineOrchestrator(self.db_path)
        result = await orchestrator.reprocess(message_id=999999, reader=None, writer=None)
        self.assertFalse(result)

    async def test_run_message_persists_pipeline_warning_events(self):
        message_id = self._create_sample_message()
        orchestrator = PipelineOrchestrator(self.db_path)
        orchestrator._build_pipelines = lambda: [_WarningPipeline()]  # type: ignore[method-assign]

        await orchestrator.run_message(
            message_id=message_id,
            msg_data={"envelope": {"dataMessage": {"message": "hej"}}},
            reader=None,
            writer=None,
        )

        runs = get_runs_for_message(self.db_path, message_id)
        self.assertEqual(len(runs), 1)

        events = get_events_for_run(self.db_path, runs[0]["id"])
        warning_events = [event for event in events if event["event_type"] == "pipeline_warning"]
        self.assertEqual(len(warning_events), 1)
        self.assertEqual(warning_events[0]["details"]["field"], "sagesman")
        self.assertEqual(warning_events[0]["details"]["value"], "2A GRUPP")

    async def test_build_pipelines_defaults_include_fors_after_seven_s(self):
        orchestrator = PipelineOrchestrator(self.db_path)

        with patch("oden.pipeline_orchestrator.cfg.ENABLED_PIPELINES", []):
            pipelines = orchestrator._build_pipelines()

        self.assertEqual(
            [pipeline.name for pipeline in pipelines], ["group_filter", "seven_s", "fors", "generic_template"]
        )
