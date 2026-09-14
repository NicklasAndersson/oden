"""Mission-package ingestion: the Marti file store as a second inbound path.

The fixtures are a real package captured off a live TAK Server 5.7 — an 8S sent
from ATAK-CIV with a photo attached. It is the whole reason this path exists:
such a report never appears on the CoT broadcast stream at all.

No network anywhere in here; :func:`oden.tak.marti.unpack` is pure, and the poller
is driven with stubs.
"""

import base64
import io
import unittest
import zipfile
from pathlib import Path

from oden.tak import marti
from oden.tak.cot import cot_to_inbound
from oden.tak.eight_s import is_8s_report
from oden.tak.listener import build_envelope

_FIX = Path(__file__).parent / "fixtures" / "tak"


def _load(name: str) -> bytes:
    return (_FIX / name).read_bytes()


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, blob in entries.items():
            archive.writestr(name, blob)
    return buffer.getvalue()


_COT = (
    b"<event version='2.0' uid='8S.x' type='a-h-G' how='h-g-i-g-o' "
    b"time='2026-09-14T20:20:12.780Z' start='2026-09-14T20:20:12.780Z' stale='2026-09-14T20:25:12.780Z'>"
    b"<point lat='59.19' lon='17.63' hae='9999999.0' ce='9999999.0' le='9999999.0'/>"
    b"<detail><contact callsign='8S-AREA99-142218'/></detail></event>"
)


class UnpackRealPackageTest(unittest.TestCase):
    """The captured package must yield the same CoT a broadcast event would."""

    def test_the_embedded_cot_parses_as_a_normal_8s_report(self):
        package = marti.unpack(_load("mission_package_8s.zip"))
        self.assertIsNotNone(package)
        cot = cot_to_inbound(package.cot)
        self.assertIsNotNone(cot)
        self.assertEqual(cot.cot_type, "a-h-G")
        self.assertEqual(cot.callsign, "8S-AREA99-142218")
        self.assertTrue(is_8s_report(cot))
        self.assertEqual(cot.custom_report["Informant"], "AREA99")
        self.assertEqual(cot.custom_report["Strength Type"], "eer")

    def test_atak_s_empty_photo_is_counted_and_dropped(self):
        """The real capture packs a 0-byte JPEG. An empty file in the vault is worse than none."""
        package = marti.unpack(_load("mission_package_8s.zip"))
        self.assertEqual(package.attachments, [])
        self.assertEqual(package.skipped_empty, 1)

    def test_a_real_photo_survives_with_its_filename(self):
        package = marti.unpack(_load("mission_package_8s_with_image.zip"))
        self.assertEqual(len(package.attachments), 1)
        name, blob = package.attachments[0]
        self.assertEqual(name, "20260914_221939.jpg")  # directory part stripped
        self.assertTrue(blob.startswith(b"\x89PNG"))
        self.assertEqual(package.skipped_empty, 0)

    def test_the_manifest_is_never_treated_as_an_attachment(self):
        package = marti.unpack(_load("mission_package_8s_with_image.zip"))
        self.assertNotIn("manifest.xml", [name for name, _ in package.attachments])


class UnpackGuardTest(unittest.TestCase):
    """The zip comes off the network, so every limit has to hold."""

    def test_a_package_without_cot_is_not_ours(self):
        self.assertIsNone(marti.unpack(_zip({"transfer/notes.txt": b"hej"})))

    def test_garbage_is_rejected_without_raising(self):
        self.assertIsNone(marti.unpack(b"inte en zip alls"))

    def test_path_traversal_entries_are_dropped(self):
        blob = _zip({"a.cot": _COT, "../../etc/passwd": b"x" * 10, "ok/photo.jpg": b"y" * 10})
        package = marti.unpack(blob)
        names = [name for name, _ in package.attachments]
        self.assertEqual(names, ["photo.jpg"])

    def test_absolute_paths_are_dropped(self):
        package = marti.unpack(_zip({"a.cot": _COT, "/tmp/evil.jpg": b"y" * 10}))
        self.assertEqual(package.attachments, [])

    def test_too_many_entries_is_refused(self):
        entries = {"a.cot": _COT}
        entries.update({f"f{i}.bin": b"x" for i in range(marti.MAX_ENTRIES + 1)})
        self.assertIsNone(marti.unpack(_zip(entries)))

    def test_an_oversized_attachment_is_skipped_but_the_report_survives(self):
        blob = _zip({"a.cot": _COT, "huge.jpg": b"x" * (marti.MAX_ATTACHMENT_BYTES + 1)})
        package = marti.unpack(blob)
        self.assertIsNotNone(package)  # the report still becomes a note
        self.assertEqual(package.attachments, [])

    def test_a_zip_bomb_is_refused(self):
        blob = _zip({"a.cot": _COT, "bomb.bin": b"\0" * (marti.MAX_UNCOMPRESSED_BYTES + 1)})
        self.assertIsNone(marti.unpack(blob))


class SearchParsingTest(unittest.TestCase):
    def test_rows_without_a_hash_are_ignored(self):
        rows = {"results": [{"Name": "a.zip"}, {"Hash": "abc", "Name": "b.zip", "Size": "12"}]}
        files = self._parse(rows)
        self.assertEqual([f.hash for f in files], ["abc"])
        self.assertEqual(files[0].size, 12)

    def test_a_bad_size_does_not_break_the_row(self):
        files = self._parse({"results": [{"Hash": "abc", "Size": "inte ett tal"}]})
        self.assertEqual(files[0].size, 0)

    def test_only_zips_are_treated_as_mission_packages(self):
        files = self._parse({"results": [{"Hash": "a", "Name": "foto.jpg"}, {"Hash": "b", "Name": "p.zip"}]})
        self.assertEqual([f.name for f in files if f.looks_like_mission_package], ["p.zip"])

    @staticmethod
    def _parse(payload: dict) -> list[marti.MartiFile]:
        """Drive marti.search without a socket by stubbing the one HTTP call."""
        import json
        from unittest import mock

        with mock.patch.object(marti, "_get", return_value=json.dumps(payload).encode()):
            return marti.search("https://example.invalid", None)


class EnvelopeAttachmentTest(unittest.TestCase):
    """The envelope has to match what attachment_handler.save_attachments expects."""

    def test_attachments_are_base64_with_their_filename(self):
        cot = cot_to_inbound(_COT)
        envelope = build_envelope(cot, "TAK Inkommande", [("foto.jpg", b"bytes here")])
        attachments = envelope["envelope"]["dataMessage"]["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["filename"], "foto.jpg")
        self.assertEqual(base64.b64decode(attachments[0]["data"]), b"bytes here")

    def test_no_attachments_gives_the_old_shape_exactly(self):
        """A broadcast CoT must produce byte-identical output to before this feature."""
        cot = cot_to_inbound(_COT)
        self.assertEqual(build_envelope(cot, "g")["envelope"]["dataMessage"]["attachments"], [])


class MartiBaseUrlTest(unittest.TestCase):
    def test_the_api_port_replaces_the_cot_port(self):
        self.assertEqual(marti.marti_base_url("ssl://tak.example:8089", 8443), "https://tak.example:8443")

    def test_a_url_without_host_is_refused(self):
        with self.assertRaises(ValueError):
            marti.marti_base_url("inte en url", 8443)


class PackageSeenTest(unittest.TestCase):
    """Without a memory of what was taken, every poll re-imports the whole archive."""

    def setUp(self) -> None:
        import tempfile

        from oden.config_db import init_db

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "config.db"
        init_db(self.db)

    def test_an_empty_cache_starts_empty(self):
        from oden.tak.listener import load_package_seen

        self.assertEqual(load_package_seen(self.db), set())

    def test_a_remembered_package_survives_a_restart(self):
        from oden.tak.listener import load_package_seen, remember_package

        remember_package(self.db, "abc123", "paket.zip", "2026-09-14T20:20:13.000Z")
        self.assertEqual(load_package_seen(self.db), {"abc123"})

    def test_remembering_the_same_hash_twice_is_harmless(self):
        from oden.tak.listener import load_package_seen, remember_package

        remember_package(self.db, "abc123", "paket.zip", "t")
        remember_package(self.db, "abc123", "paket.zip", "t")
        self.assertEqual(load_package_seen(self.db), {"abc123"})

    def test_a_broken_database_means_an_empty_cache_not_a_crash(self):
        from oden.tak.listener import load_package_seen

        broken = Path(self._tmp.name) / "trasig.db"
        broken.write_bytes(b"inte en databas")
        self.assertEqual(load_package_seen(broken), set())


class PollerTest(unittest.IsolatedAsyncioTestCase):
    """The poll loop itself, driven with stubs — no socket, no real server.

    The loop is ended by making its own ``asyncio.sleep`` raise ``CancelledError``
    after a set number of rounds, which is also exactly how the listener stops it.
    """

    def setUp(self) -> None:
        import tempfile
        from unittest import mock

        from oden import config as cfg
        from oden.config_db import init_db

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "config.db"
        init_db(self.db)
        patcher = mock.patch.object(cfg, "CONFIG_DB", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.notes: list[tuple[str, tuple[str, ...]]] = []

    async def _poll(self, files, blobs, *, rounds: int = 1):
        import asyncio
        import contextlib
        from unittest import mock

        from oden.tak import listener

        bridge = mock.Mock()
        bridge.settings = {"inbound_types": ["a-h-G"], "inbound_fetch_packages": True}
        bridge.pytak_config = {"COT_URL": "ssl://tak.example:8089"}
        bridge.rx_total = bridge.rx_filtered = bridge.received_count = 0

        remaining = rounds

        async def fake_sleep(_delay):
            nonlocal remaining
            if remaining <= 0:
                raise asyncio.CancelledError
            remaining -= 1

        async def capture(cot, group_name, orchestrator, *, attachments=()):
            self.notes.append((cot.uid, tuple(name for name, _ in attachments)))

        filt = listener.InboundFilter({"inbound_types": ["a-h-G"]})
        with (
            mock.patch.object(marti, "ssl_context", return_value=None),
            mock.patch.object(marti, "search", return_value=files),
            mock.patch.object(marti, "fetch", side_effect=lambda _url, digest, _ctx: blobs.get(digest)),
            mock.patch.object(listener, "_create_note", capture),
            mock.patch.object(asyncio, "sleep", fake_sleep),
            contextlib.suppress(asyncio.CancelledError),
        ):
            await listener.run_package_poller(bridge, filt=filt, group_name="TAK Inkommande", orchestrator=mock.Mock())
        return bridge

    async def test_the_first_round_seeds_without_importing_the_archive(self):
        """A server keeps months of packages; importing them all would bury the vault."""
        from oden.tak.listener import load_package_seen

        files = [marti.MartiFile("h1", "gammalt.zip", "2026-01-01", "", "", 10)]
        await self._poll(files, {"h1": _load("mission_package_8s_with_image.zip")})
        self.assertEqual(self.notes, [])
        self.assertEqual(load_package_seen(self.db), {"h1"})

    async def test_a_package_arriving_after_seeding_becomes_a_note_with_its_photo(self):
        from oden.tak.listener import remember_package

        remember_package(self.db, "gammal", "gammalt.zip", "2026-01-01")  # not a first run any more
        files = [
            marti.MartiFile("gammal", "gammalt.zip", "2026-01-01", "", "", 10),
            marti.MartiFile("ny", "nytt.zip", "2026-09-14", "", "", 10),
        ]
        await self._poll(files, {"ny": _load("mission_package_8s_with_image.zip")})
        self.assertEqual(len(self.notes), 1)
        _uid, attachments = self.notes[0]
        self.assertEqual(attachments, ("20260914_221939.jpg",))

    async def test_the_real_package_with_atak_s_empty_photo_still_becomes_a_note(self):
        """Losing the photo is bad; losing the whole report is what this feature fixes."""
        from oden.tak.listener import remember_package

        remember_package(self.db, "gammal", "g.zip", "2026-01-01")
        files = [marti.MartiFile("ny", "nytt.zip", "2026-09-14", "", "", 10)]
        await self._poll(files, {"ny": _load("mission_package_8s.zip")})
        self.assertEqual(len(self.notes), 1)
        self.assertEqual(self.notes[0][1], ())  # the 0-byte JPEG was dropped

    async def test_an_unusable_package_is_recorded_so_it_is_not_retried_forever(self):
        from oden.tak.listener import load_package_seen, remember_package

        remember_package(self.db, "gammal", "g.zip", "2026-01-01")
        files = [marti.MartiFile("trasig", "trasig.zip", "2026-09-14", "", "", 10)]
        await self._poll(files, {"trasig": b"inte en zip"})
        self.assertEqual(self.notes, [])
        self.assertIn("trasig", load_package_seen(self.db))

    async def test_rows_that_are_not_zips_are_never_downloaded(self):
        from oden.tak.listener import load_package_seen, remember_package

        remember_package(self.db, "gammal", "g.zip", "2026-01-01")
        files = [marti.MartiFile("foto", "bara-ett-foto.jpg", "2026-09-14", "", "", 10)]
        await self._poll(files, {})
        self.assertNotIn("foto", load_package_seen(self.db))

    async def test_a_package_already_taken_is_not_imported_twice(self):
        from oden.tak.listener import remember_package

        remember_package(self.db, "ny", "nytt.zip", "2026-09-14")
        files = [marti.MartiFile("ny", "nytt.zip", "2026-09-14", "", "", 10)]
        await self._poll(files, {"ny": _load("mission_package_8s_with_image.zip")}, rounds=2)
        self.assertEqual(self.notes, [])


if __name__ == "__main__":
    unittest.main()
