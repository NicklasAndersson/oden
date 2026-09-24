"""Rapportformat: formats defined as settings, run as branch steps like the built-ins."""

import copy
import tempfile
import unittest
import unittest.mock
import zoneinfo
from pathlib import Path

from oden.config_db import init_db
from oden.dry_run import build_test_message, dry_run
from oden.flow_db import get_flow_item
from oden.messages_db import create_raw_message
from oden.pipeline_orchestrator import PipelineOrchestrator
from oden.report_formats import STARTERS, FormatReportPipeline, normalize_format, parse
from oden.routing import normalize_routing

FORS_TEXT = """FORS-RAPPORT
Till: Stab
Från: Pluton 2
TNR: 241430
F – Förbandets position
33V VN 12345 67890
O – Orientering
Lugnt i området
R – Redogörelse för vht
Genomförd: Patrull norr
Pågående: Vila
Planerad: Patrull söder
SLUT!
"""

ANMALAN = {
    "name": "Anmälan",
    "headers": ["ANMÄLAN"],
    "fields": [
        {"label": "TNR", "required": True},
        {"label": "Plats", "type": "mgrs"},
        {"label": "Vad", "required": True, "aliases": ["Händelse"]},
    ],
    "tnr_field": "tnr",
    "file_prefix": "ANM",
}


class NormalizeFormatTest(unittest.TestCase):
    def test_ids_and_keys_are_generated(self):
        fmt = normalize_format({**ANMALAN, "fields": [*ANMALAN["fields"], {"label": "Förband & enhet"}]})
        self.assertEqual(fmt["id"], "anmalan")
        self.assertEqual([f["key"] for f in fmt["fields"]], ["tnr", "plats", "vad", "forband_enhet"])
        self.assertEqual(fmt["fields"][1]["type"], "mgrs")
        self.assertEqual(fmt["report_type"], "Anmälan-rapport")

    def test_rejects_bad_definitions(self):
        for bad in (
            {**ANMALAN, "headers": []},
            {**ANMALAN, "fields": [], "sections": []},
            {**ANMALAN, "tnr_field": "nope"},
            {**ANMALAN, "file_prefix": "A B"},
            {**ANMALAN, "fields": [{"label": "X", "key": "a"}, {"label": "Y", "key": "a"}], "tnr_field": ""},
            {**ANMALAN, "template": "{% if %}"},
        ):
            with self.assertRaises(ValueError):
                normalize_format(bad)

    def test_every_starter_is_a_valid_format(self):
        for starter in STARTERS.values():
            normalize_format(starter)


class ParseTest(unittest.TestCase):
    def test_fors_starter_reads_fields_and_sections(self):
        parsed = parse(normalize_format(STARTERS["fors"]), FORS_TEXT)
        self.assertEqual(parsed["missing"], [])
        self.assertEqual(parsed["fields"]["fran"], "Pluton 2")
        self.assertEqual(parsed["fields"]["genomford"], "Patrull norr")
        self.assertEqual(parsed["sections"]["orientering"], "Lugnt i området")
        self.assertEqual(parsed["sections"]["forbandets_position"], "33V VN 12345 67890")

    def test_missing_required_and_other_lines(self):
        parsed = parse(normalize_format(ANMALAN), "ANMÄLAN\nTNR: 241430\nnågot utan etikett\nhändelse: bil")
        self.assertEqual(parsed["missing"], [])
        self.assertEqual(parsed["fields"]["vad"], "bil")
        self.assertEqual(parsed["other"], ["något utan etikett"])
        self.assertEqual(parse(normalize_format(ANMALAN), "ANMÄLAN\nTNR: 241430")["missing"], ["Vad"])


class _Base(unittest.IsolatedAsyncioTestCase):
    formats = [normalize_format(ANMALAN)]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name) / "vault"
        self.vault.mkdir()
        self.db = Path(tmp.name) / "config.db"
        init_db(self.db)
        self.routing = normalize_routing(
            {
                "branches": [
                    {
                        "id": "underhall",
                        "name": "Underhåll",
                        "steps": [
                            {"pipeline": "format:anmalan", "config": {"vault_subdir": "Anmälningar"}},
                            {"pipeline": "generic_template", "enabled": False},
                        ],
                    },
                    {"id": "main", "name": "Huvudgren", "steps": ["format:borttagen"]},
                    {
                        "id": "pedars",
                        "name": "Bara PEDARS",
                        "steps": ["pedars", {"pipeline": "generic_template", "config": {"vault_subdir": "Övrigt"}}],
                    },
                ],
                "assign": {"group:Underhåll": "underhall", "group:Pluton": "pedars"},
                "default": "main",
            }
        )
        patches = [
            unittest.mock.patch("oden.config.VAULT_PATH", str(self.vault)),
            unittest.mock.patch("oden.config.CONFIG_DB", self.db),
            unittest.mock.patch("oden.config.ROUTING", self.routing),
            unittest.mock.patch("oden.config.REPORT_FORMATS", copy.deepcopy(self.formats)),
            unittest.mock.patch("oden.config.GROUP_SPLIT_ENABLED", True),
            unittest.mock.patch("oden.config.TIMEZONE", zoneinfo.ZoneInfo("Europe/Stockholm")),
            unittest.mock.patch("oden.config.PIPELINE_SETTINGS", {}),
            unittest.mock.patch("oden.pipeline_orchestrator.get_tak_bridge", return_value=None),
            unittest.mock.patch("oden.dry_run.publish_to_tak", return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class FormatPipelineTest(_Base):
    async def _run(self, text, group):
        msg = build_test_message(text, f"group:{group}")
        message_id = create_raw_message(self.db, "+46700000000", msg)
        await PipelineOrchestrator(self.db).run_message(message_id=message_id, msg_data=msg, reader=None, writer=None)
        return get_flow_item(self.db, message_id)

    async def test_format_step_writes_its_note_in_the_branch_subdir(self):
        item = await self._run("ANMÄLAN\nTNR: 241430\nVad: Bil utan plåtar", "Underhåll")
        written = self.vault / "Underhåll" / "Anmälningar" / "ANM241430.md"
        self.assertTrue(written.exists(), list(self.vault.rglob("*")))
        content = written.read_text()
        self.assertIn("typ: Anmälan-rapport", content)
        self.assertIn('vad: "Bil utan plåtar"', content)
        self.assertIn("**Vad:** Bil utan plåtar", content)
        self.assertEqual(item["status"], "processed")

    async def test_fallback_off_keeps_the_rest_only_in_flow(self):
        item = await self._run("Hej allihop", "Underhåll")
        self.assertEqual(item["status"], "ignored")
        self.assertEqual(list(self.vault.rglob("*.md")), [])

    async def test_fallback_writes_in_the_branch_folder(self):
        await self._run("Framme", "Pluton")
        self.assertEqual(
            [p.parent.relative_to(self.vault).as_posix() for p in self.vault.rglob("*.md")], ["Pluton/Övrigt"]
        )
        preview = await dry_run(build_test_message("Framme", "group:Pluton"))
        self.assertTrue(preview["output_file"].startswith("Pluton/Övrigt/"))

    async def test_step_of_a_deleted_format_is_skipped(self):
        item = await self._run("ANMÄLAN\nTNR: 241430\nVad: x", "Annan")
        self.assertEqual([s["pipeline"] for s in item["steps"]], ["router", "generic_template"])

    async def test_template_renders_the_body(self):
        fmt = normalize_format({**ANMALAN, "template": "Rapport {{ tnr }}: {{ fields.vad | upper }}"})
        preview = await FormatReportPipeline(fmt).preview(
            build_test_message("ANMÄLAN\nTNR: 241430\nVad: bil", "group:G")
        )
        self.assertTrue(preview["handled"])
        self.assertIn("Rapport 241430: BIL", preview["content"])
        self.assertEqual(list(self.vault.rglob("*")), [])

    async def test_testruta_uses_format_steps(self):
        result = await dry_run(build_test_message("ANMÄLAN\nTNR: 241430", "group:Underhåll"))
        self.assertEqual(result["steps"][0]["pipeline"], "format:anmalan")
        self.assertEqual(result["steps"][0]["outcome"], "failed")
        self.assertIn("Vad", result["steps"][0]["reason"])
        self.assertEqual(result["steps"][-1]["outcome"], "ignored")


class FormatApiTest(_Base):
    async def test_list_save_and_test(self):
        from aiohttp.test_utils import TestClient, TestServer

        from oden.config_db import get_all_config
        from oden.web_server import create_app

        async with TestClient(TestServer(create_app())) as client:
            listed = await (await client.get("/api/report-formats")).json()
            routing = await (await client.get("/api/routing")).json()
            removing = await client.put("/api/report-formats", json={"formats": []})
            removing_error = (await removing.json())["error"]
            added = await client.put(
                "/api/report-formats", json={"formats": [*listed["formats"], {**ANMALAN, "name": "Anmälan 2"}]}
            )
            tested = await (
                await client.post("/api/report-formats/test", json={"format": STARTERS["fors"], "text": FORS_TEXT})
            ).json()
            stored = get_all_config(self.db)["report_formats"]
            page = await (await client.get("/")).text()

        self.assertEqual(listed["used_in"], {"anmalan": ["Underhåll"], "borttagen": ["Huvudgren"]})
        self.assertIn("fors", [b["name"] for b in listed["builtins"]])
        self.assertIn("format:anmalan", [p["name"] for p in routing["pipelines"]])
        self.assertEqual(routing["pipelines"][-1]["name"], "generic_template")
        self.assertEqual(removing.status, 400)
        self.assertIn("Underhåll", removing_error)
        self.assertEqual(added.status, 200)
        self.assertEqual([f["id"] for f in stored], ["anmalan", "anmalan-2"])
        self.assertTrue(tested["matched"])
        self.assertTrue(tested["handled"])
        self.assertIn("## O – Orientering", tested["content"])
        self.assertEqual(list(self.vault.rglob("*")), [])
        self.assertIn('id="formats-list"', page)
        self.assertIn("function saveFormat", page)


class SafetyTest(unittest.TestCase):
    def test_trailing_comment_search_matches_the_old_regex(self):
        import random
        import re

        from oden.pipelines.structured_report import iter_nonempty_lines, trailing_obsidian_comment

        old = re.compile(r"\n%%\n.*?\n%%[ \t]*$", re.DOTALL)
        rng = random.Random(7)
        pieces = ["\n", "%%", "%", " ", "\t", "a", "\n%%\n", "\n%%"]
        for _ in range(5000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 12)))
            match = old.search(text)
            self.assertEqual(trailing_obsidian_comment(text), match.group(0).strip() if match else "", repr(text))
            expected = [ln.strip() for ln in old.sub("", text).splitlines() if ln.strip()]
            self.assertEqual(iter_nonempty_lines(text), expected, repr(text))

    def test_trailing_comment_search_is_linear(self):
        import time

        from oden.pipelines.structured_report import trailing_obsidian_comment

        text = "\n%%\n" * 50000 + "x"
        started = time.perf_counter()
        trailing_obsidian_comment(text)
        self.assertLess(time.perf_counter() - started, 0.5)

    def test_report_path_never_leaves_the_vault(self):
        from oden.pipelines.structured_report import build_report_filepath

        with (
            tempfile.TemporaryDirectory() as tmp,
            unittest.mock.patch("oden.config.VAULT_PATH", tmp),
            unittest.mock.patch("oden.config.GROUP_SPLIT_ENABLED", True),
        ):
            for prefix, tnr in (("../", "x"), ("A", "/../../etc/x"), ("A/", "../../x")):
                with self.assertRaises(ValueError):
                    build_report_filepath("G", None, tnr, prefix=prefix, create=False)
            path, _ = build_report_filepath("../G", None, "241430", prefix="ANM", create=False)
            self.assertTrue(path.startswith(tmp))

    def test_format_tnr_is_cleaned_for_the_file_name(self):
        import datetime

        pipeline = FormatReportPipeline(normalize_format(ANMALAN))
        now = datetime.datetime(2026, 9, 24, 14, 30)
        self.assertEqual(pipeline.report_tnr({"tnr": "../24 14:30"}, now), "241430")
        self.assertEqual(pipeline.report_tnr({"tnr": "///"}, now), "241430")
