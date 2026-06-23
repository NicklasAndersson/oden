"""Tests for DB retention cleanup."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from oden.config_db import init_db
from oden.messages_db import create_raw_message
from oden.pipelines_db import append_pipeline_event, start_pipeline_run
from oden.retention_db import cleanup_old_data


class TestRetentionCleanup(unittest.TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            self.db_path = Path(tmp.name)
        self.db_path.unlink(missing_ok=True)
        init_db(self.db_path)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def _insert_message(self) -> int:
        return create_raw_message(
            self.db_path,
            "+46700000000",
            {
                "account": "+46700000000",
                "envelope": {
                    "timestamp": 1700000000000,
                    "sourceNumber": "+46701111111",
                    "sourceName": "Tester",
                    "dataMessage": {"message": "hej"},
                },
            },
        )

    def _set_old_message_timestamp(self, message_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE raw_messages SET created_at = ? WHERE id = ?",
                ("2020-01-01T00:00:00.000Z", message_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _set_old_event_timestamp(self, run_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE pipeline_events SET occurred_at = ? WHERE run_id = ?",
                ("2020-01-01T00:00:00.000Z", run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _count_rows(self, table: str) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            return int(cursor.fetchone()[0])
        finally:
            conn.close()

    def test_cleanup_removes_old_messages_and_related_runs_events(self):
        old_message_id = self._insert_message()
        new_message_id = self._insert_message()

        old_run_id = start_pipeline_run(self.db_path, old_message_id, "generic_template")
        new_run_id = start_pipeline_run(self.db_path, new_message_id, "generic_template")

        append_pipeline_event(self.db_path, old_run_id, "pipeline_started", {"kind": "old"})
        append_pipeline_event(self.db_path, new_run_id, "pipeline_started", {"kind": "new"})

        self._set_old_message_timestamp(old_message_id)

        summary = cleanup_old_data(self.db_path, 30)

        self.assertEqual(summary["deleted_raw_messages"], 1)
        self.assertEqual(summary["deleted_pipeline_runs"], 1)
        self.assertEqual(summary["deleted_pipeline_events"], 1)

        self.assertEqual(self._count_rows("raw_messages"), 1)
        self.assertEqual(self._count_rows("pipeline_runs"), 1)
        self.assertEqual(self._count_rows("pipeline_events"), 1)

    def test_cleanup_removes_old_events_even_if_message_is_kept(self):
        message_id = self._insert_message()
        run_id = start_pipeline_run(self.db_path, message_id, "generic_template")
        append_pipeline_event(self.db_path, run_id, "pipeline_started", {"kind": "old_event"})

        self._set_old_event_timestamp(run_id)

        summary = cleanup_old_data(self.db_path, 30)

        self.assertEqual(summary["deleted_raw_messages"], 0)
        self.assertEqual(summary["deleted_pipeline_runs"], 0)
        self.assertEqual(summary["deleted_pipeline_events"], 1)

        self.assertEqual(self._count_rows("raw_messages"), 1)
        self.assertEqual(self._count_rows("pipeline_runs"), 1)
        self.assertEqual(self._count_rows("pipeline_events"), 0)

    def test_cleanup_noop_for_invalid_retention_days(self):
        message_id = self._insert_message()
        run_id = start_pipeline_run(self.db_path, message_id, "generic_template")
        append_pipeline_event(self.db_path, run_id, "pipeline_started", None)

        summary = cleanup_old_data(self.db_path, 0)

        self.assertEqual(summary["deleted_raw_messages"], 0)
        self.assertEqual(summary["deleted_pipeline_runs"], 0)
        self.assertEqual(summary["deleted_pipeline_events"], 0)
        self.assertEqual(self._count_rows("raw_messages"), 1)
        self.assertEqual(self._count_rows("pipeline_runs"), 1)
        self.assertEqual(self._count_rows("pipeline_events"), 1)


if __name__ == "__main__":
    unittest.main()
