"""Tests for the Flöde view: reasons recorded by the orchestrator, the flow read
model in ``oden.flow_db`` and the ``/api/flow`` endpoints."""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from oden.config_db import init_db
from oden.flow_db import flow_summary, get_flow_item, list_flow, source_key
from oden.messages_db import create_raw_message, update_message_status
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.web_server import create_app


def _signal_msg(body="hej", group="Spaning Norr"):
    return {
        "envelope": {
            "sourceNumber": "+46701111111",
            "sourceName": "Test",
            "timestamp": 1710000000000,
            "dataMessage": {"message": body, "groupV2": {"id": "grp-1", "name": group}},
        }
    }


def _tak_msg():
    return {
        "envelope": {
            "sourceName": "ORM 21",
            "sourceNumber": "tak:ANDROID-1",
            "sourceUuid": "tak:ANDROID-1",
            "timestamp": 1710000001000,
            "_source": "tak",
            "dataMessage": {"message": "TAK-OBSERVATION", "groupV2": {"id": "tak", "name": "TAK"}},
        }
    }


class _Skip:
    name = "skipper"

    async def run(self, *, msg_data, reader, writer):
        self.last_reason = "Ingen rubrik ”7S RAPPORT”"
        return False


class _SideEffect:
    name = "side"

    async def run(self, *, msg_data, reader, writer):
        self.last_side_effect = "Publicerad till TAK"
        return False


class _Handle:
    name = "handler"

    async def run(self, *, msg_data, reader, writer):
        self.last_reason = "Rubriken matchade"
        self.last_output_file = "/vault/Spaning Norr/7S-1.md"
        return True


class _Silent:
    """Handles without setting anything — must not inherit a previous reason."""

    name = "handler"

    async def run(self, *, msg_data, reader, writer):
        return True


class TestFlowRecording(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "config.db"
        init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    async def _run(self, pipelines, msg=None):
        msg = msg or _signal_msg()
        message_id = create_raw_message(self.db_path, "+46700000000", msg)
        orchestrator = PipelineOrchestrator(self.db_path)
        orchestrator._build_pipelines = lambda: pipelines  # type: ignore[method-assign]
        await orchestrator.run_message(message_id=message_id, msg_data=msg, reader=None, writer=None)
        return message_id

    async def test_reasons_side_effects_and_output_file_are_recorded(self):
        message_id = await self._run([_SideEffect(), _Skip(), _Handle()])

        item = get_flow_item(self.db_path, message_id)
        self.assertEqual(item["status"], "processed")
        steps = {s["pipeline"]: s for s in item["steps"]}
        self.assertEqual(steps["side"]["outcome"], "skipped")
        self.assertEqual(steps["side"]["side_effect"], "Publicerad till TAK")
        self.assertEqual(steps["skipper"]["reason"], "Ingen rubrik ”7S RAPPORT”")
        self.assertEqual(steps["handler"]["outcome"], "handled")
        self.assertEqual(steps["handler"]["reason"], "Rubriken matchade")
        self.assertEqual(steps["handler"]["output_file"], "/vault/Spaning Norr/7S-1.md")
        self.assertIsInstance(item["envelope_raw"], dict)

    async def test_reused_pipeline_does_not_leak_previous_reason(self):
        handler = _Handle()
        await self._run([handler])
        handler.run = _Silent().run  # same instance, now silent
        second = await self._run([handler])

        step = get_flow_item(self.db_path, second)["steps"][0]
        self.assertIsNone(step["reason"])
        self.assertIsNone(step["output_file"])

    async def test_reprocess_shows_only_latest_attempt(self):
        message_id = await self._run([_Skip(), _Handle()])
        orchestrator = PipelineOrchestrator(self.db_path)
        orchestrator._build_pipelines = lambda: [_Skip(), _Handle()]  # type: ignore[method-assign]
        await orchestrator.reprocess(message_id=message_id, reader=None, writer=None)

        item = get_flow_item(self.db_path, message_id)
        self.assertEqual(item["attempts"], 2)
        self.assertEqual([s["pipeline"] for s in item["steps"]], ["skipper", "handler"])

    async def test_ignored_message_marks_handler_as_ignored(self):
        from oden.messages_db import STATUS_IGNORED

        class _Filter(_Handle):
            name = "group_filter"
            status_on_handle = STATUS_IGNORED

        message_id = await self._run([_Filter()])
        self.assertEqual(get_flow_item(self.db_path, message_id)["steps"][0]["outcome"], "ignored")


class TestFlowReadModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "config.db"
        init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_key(self):
        self.assertEqual(source_key("+4670", "tak:X"), "tak")
        self.assertEqual(source_key("+4670", "+4671"), "signal:+4670")

    def test_filters_by_source_and_hides_empty(self):
        sig = create_raw_message(self.db_path, "+46700000000", _signal_msg())
        tak = create_raw_message(self.db_path, "+46700000000", _tak_msg())
        create_raw_message(self.db_path, "+46700000000", _signal_msg(body=None))

        self.assertEqual([m["id"] for m in list_flow(self.db_path)], [tak, sig])
        self.assertEqual([m["id"] for m in list_flow(self.db_path, source="tak")], [tak])
        self.assertEqual([m["id"] for m in list_flow(self.db_path, source="signal:+46700000000")], [sig])
        self.assertEqual(len(list_flow(self.db_path, has_content_only=False)), 3)

        summary = flow_summary(self.db_path)
        self.assertEqual(summary["sources"], {"signal:+46700000000": 1, "tak": 1})
        self.assertEqual(summary["hidden_without_content"], 1)

    def test_status_filter(self):
        a = create_raw_message(self.db_path, "+46700000000", _signal_msg())
        b = create_raw_message(self.db_path, "+46700000000", _signal_msg())
        update_message_status(self.db_path, a, "failed")
        update_message_status(self.db_path, b, "processed")
        self.assertEqual([m["id"] for m in list_flow(self.db_path, status="failed")], [a])


class TestGenericPipelineOutcome(unittest.IsolatedAsyncioTestCase):
    async def test_write_error_fails_the_run(self):
        from oden.pipeline_orchestrator import _GenericPipeline
        from oden.processing import ProcessOutcome

        pipeline = _GenericPipeline()
        with (
            unittest.mock.patch(
                "oden.pipeline_orchestrator.process_message",
                return_value=ProcessOutcome("error", "Kunde inte skriva filen: nope"),
            ),
            self.assertRaises(OSError),
        ):
            await pipeline.run(msg_data={}, reader=None, writer=None)

    async def test_reason_and_path_are_exposed(self):
        from oden.pipeline_orchestrator import _GenericPipeline
        from oden.processing import ProcessOutcome

        pipeline = _GenericPipeline()
        with unittest.mock.patch(
            "oden.pipeline_orchestrator.process_message",
            return_value=ProcessOutcome("wrote", "Ny fil", "/v/a.md"),
        ):
            self.assertTrue(await pipeline.run(msg_data={}, reader=None, writer=None))
        self.assertEqual(pipeline.last_reason, "Ny fil")
        self.assertEqual(pipeline.last_output_file, "/v/a.md")


class TestFlowAPI(AioHTTPTestCase):
    async def get_application(self):
        return create_app(setup_mode=False)

    async def test_list_and_detail_with_output_preview(self):
        from oden.pipelines_db import append_pipeline_event, complete_pipeline_run, start_pipeline_run

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            vault = Path(tmpdir) / "vault"
            (vault / "Spaning Norr").mkdir(parents=True)
            note = vault / "Spaning Norr" / "7S-1.md"
            note.write_text("# 7S RAPPORT 1\n", encoding="utf-8")
            init_db(db_path)

            message_id = create_raw_message(db_path, "+46700000000", _signal_msg())
            run_id = start_pipeline_run(db_path, message_id, "seven_s")
            complete_pipeline_run(db_path, run_id, output_file=str(note))
            append_pipeline_event(db_path, run_id, "pipeline_completed", {"pipeline": "seven_s", "reason": "Matchade"})
            update_message_status(db_path, message_id, "processed")

            with (
                unittest.mock.patch("oden.web_handlers.message_handlers.cfg.CONFIG_DB", db_path),
                unittest.mock.patch("oden.web_handlers.message_handlers.cfg.VAULT_PATH", str(vault)),
            ):
                resp = await self.client.get("/api/flow")
                detail = await self.client.get(f"/api/flow/{message_id}")
                missing = await self.client.get("/api/flow/99999")

            self.assertEqual(resp.status, 200)
            payload = await resp.json()
            self.assertEqual(payload["messages"][0]["id"], message_id)
            step = payload["messages"][0]["steps"][0]
            self.assertEqual(step["reason"], "Matchade")
            self.assertEqual(step["output_path"], str(Path("Spaning Norr") / "7S-1.md"))
            self.assertIn("chain", payload)
            self.assertEqual(payload["summary"]["total"], 1)

            self.assertEqual(detail.status, 200)
            data = await detail.json()
            self.assertEqual(data["output"]["content"], "# 7S RAPPORT 1\n")
            self.assertEqual(data["message"]["envelope_raw"]["envelope"]["sourceName"], "Test")
            self.assertEqual(missing.status, 404)

    async def test_detail_never_reads_files_outside_the_vault(self):
        from oden.pipelines_db import complete_pipeline_run, start_pipeline_run

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "config.db"
            vault = Path(tmpdir) / "vault"
            vault.mkdir()
            secret = Path(tmpdir) / "secret.txt"
            secret.write_text("hemligt", encoding="utf-8")
            init_db(db_path)
            message_id = create_raw_message(db_path, "+46700000000", _signal_msg())
            run_id = start_pipeline_run(db_path, message_id, "generic_template")
            complete_pipeline_run(db_path, run_id, output_file=str(vault / ".." / "secret.txt"))

            with (
                unittest.mock.patch("oden.web_handlers.message_handlers.cfg.CONFIG_DB", db_path),
                unittest.mock.patch("oden.web_handlers.message_handlers.cfg.VAULT_PATH", str(vault)),
            ):
                resp = await self.client.get(f"/api/flow/{message_id}")

            self.assertEqual(resp.status, 200)
            self.assertIsNone((await resp.json())["output"])

    async def test_dashboard_has_flow_tab(self):
        resp = await self.client.get("/")
        text = await resp.text()
        self.assertIn('id="tab-flow"', text)
        self.assertIn("function fetchFlowIfVisible", text)
