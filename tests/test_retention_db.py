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


class TestRetentionBySizeAndSchedule(unittest.IsolatedAsyncioTestCase):
    """Size limit, stats, and the schedule that no longer depends on Signal traffic."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "config.db"
        init_db(self.db_path)

    def _insert(self, body: str, *, tak: bool = False) -> int:
        envelope = {"timestamp": 1700000000000, "sourceNumber": "tak:X" if tak else "+46701111111"}
        envelope["dataMessage"] = {"message": body}
        message_id = create_raw_message(self.db_path, "+46700000000", {"envelope": envelope})
        run_id = start_pipeline_run(self.db_path, message_id, "generic_template")
        append_pipeline_event(self.db_path, run_id, "pipeline_started", {"pipeline": "generic_template"})
        return message_id

    def _ids(self) -> list[int]:
        conn = sqlite3.connect(self.db_path)
        try:
            return [row[0] for row in conn.execute("SELECT id FROM raw_messages ORDER BY id")]
        finally:
            conn.close()

    def test_size_limit_removes_oldest_first(self):
        big = "x" * (400 * 1024)
        ids = [self._insert(big) for _ in range(5)]  # ~2 MB raw

        summary = cleanup_old_data(self.db_path, 30, max_mb=1)

        self.assertEqual(self._ids(), ids[-2:])
        self.assertEqual(summary["deleted_for_size"], 3)
        self.assertEqual(summary["deleted_pipeline_runs"], 3)

    def test_no_size_limit_keeps_everything(self):
        self._insert("x" * (600 * 1024))
        self._insert("x" * (600 * 1024))
        cleanup_old_data(self.db_path, 30, max_mb=0)
        self.assertEqual(len(self._ids()), 2)

    def test_storage_stats_counts_tak(self):
        from oden.retention_db import storage_stats

        self._insert("hej")
        self._insert("TAK-OBSERVATION", tak=True)
        stats = storage_stats(self.db_path)
        self.assertEqual(stats["messages"], 2)
        self.assertEqual(stats["tak_messages"], 1)
        self.assertGreater(stats["raw_bytes"], 0)
        self.assertEqual(stats["pipeline_runs"], 2)

    def test_vacuum_after_large_delete_shrinks_file(self):
        from oden.retention_db import vacuum_if_worthwhile

        for _ in range(40):
            self._insert("x" * (512 * 1024))
        before = self.db_path.stat().st_size
        cleanup_old_data(self.db_path, 30, max_mb=1)
        self.assertTrue(vacuum_if_worthwhile(self.db_path))
        self.assertLess(self.db_path.stat().st_size, before / 4)

    def test_run_cleanup_now_uses_settings_and_skips_missing_db(self):
        from unittest.mock import patch

        from oden import retention_db

        self._insert("x" * (700 * 1024))
        self._insert("x" * (700 * 1024))
        with (
            patch("oden.config.CONFIG_DB", self.db_path),
            patch("oden.config.RAW_MESSAGE_RETENTION_DAYS", 30),
            patch("oden.config.RAW_MESSAGE_MAX_MB", 1),
        ):
            summary = retention_db.run_cleanup_now()
        self.assertEqual(summary["deleted_for_size"], 1)
        self.assertIs(retention_db.last_cleanup, summary)

        missing = Path(self.tmp.name) / "nope.db"
        with patch("oden.config.CONFIG_DB", missing):
            self.assertEqual(retention_db.run_cleanup_now(), {"skipped": True})
        self.assertFalse(missing.exists())

    async def test_loop_cleans_at_startup_without_any_signal_message(self):
        import asyncio
        from unittest.mock import patch

        from oden import retention_db

        calls = []
        stop = asyncio.Event()
        with patch.object(retention_db, "run_cleanup_now", side_effect=lambda: calls.append(1) or {}):
            task = asyncio.create_task(retention_db.run_retention_loop(stop, interval=0.05))
            await asyncio.sleep(0.18)
            stop.set()
            await asyncio.wait_for(task, 1)
        self.assertGreaterEqual(len(calls), 2)


class TestStorageApi(unittest.IsolatedAsyncioTestCase):
    async def test_storage_endpoints(self):
        from unittest.mock import patch

        from aiohttp.test_utils import TestClient, TestServer

        from oden.web_server import create_app

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "config.db"
            init_db(db)
            with (
                patch("oden.config.CONFIG_DB", db),
                patch("oden.web_handlers.config_handlers.cfg.CONFIG_DB", db),
                patch("oden.config.RAW_MESSAGE_MAX_MB", 5),
            ):
                async with TestClient(TestServer(create_app())) as client:
                    stats = await (await client.get("/api/storage")).json()
                    cleaned = await (await client.post("/api/storage/cleanup")).json()
                    page = await (await client.get("/")).text()
        self.assertEqual(stats["messages"], 0)
        self.assertEqual(stats["max_mb"], 5)
        self.assertTrue(cleaned["success"])
        self.assertIn('id="cfg-raw-max-mb"', page)
        self.assertIn("function runStorageCleanup", page)
