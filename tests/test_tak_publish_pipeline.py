import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from oden.pipelines.tak_publish import TakPublishPipeline

_7S_WITH_COORDS = (
    "7S RAPPORT\nTill: A\nFrån: B\nTNR: 281430\nStund: 281430\n"
    "Ställe: 34VCM 79349 26095, Testvägen\nHändelse: Fordonskolonn\nSagesman: AQ\n"
)
_7S_NO_COMMA = _7S_WITH_COORDS.replace("34VCM 79349 26095, Testvägen", "33VXF 56007 96107")
_7S_NO_COORDS = _7S_WITH_COORDS.replace("34VCM 79349 26095, Testvägen", "Vid gamla ladan")


class FakeBridge:
    def __init__(self, running=True):
        self.is_running = running
        self.stale_seconds = 3600
        self.archive = True
        self.settings = {"callsign": "ODEN"}
        self.published: list[bytes] = []

    async def publish(self, cot: bytes) -> bool:
        self.published.append(cot)
        return True


def _msg(message: str, source: str | None = None) -> dict:
    env = {
        "sourceName": "Test",
        "sourceNumber": "+46700000000",
        "sourceUuid": "uuid-1",
        "timestamp": 1_700_000_000_000,
        "dataMessage": {"message": message, "groupV2": {"name": "g", "id": "gid"}},
    }
    if source:
        env["_source"] = source
    return {"envelope": env}


async def _run(pipeline, msg_data):
    return await pipeline.run(msg_data=msg_data, reader=None, writer=None)


class TakPublishPipelineTest(unittest.IsolatedAsyncioTestCase):
    def _patch_bridge(self, bridge):
        p = patch("oden.pipelines.tak_publish.get_tak_bridge", return_value=bridge)
        p.start()
        self.addCleanup(p.stop)

    async def test_publishes_7s_with_coords_and_is_non_consuming(self):
        bridge = FakeBridge()
        self._patch_bridge(bridge)

        handled = await _run(TakPublishPipeline(), _msg(_7S_WITH_COORDS))

        self.assertFalse(handled)  # never consumes the message
        self.assertEqual(len(bridge.published), 1)
        root = ET.fromstring(bridge.published[0])
        self.assertEqual(root.get("uid"), "ODEN.7S.281430")
        point = root.find("point")
        self.assertAlmostEqual(float(point.get("lat")), 59.7551, places=3)

    async def test_publishes_when_stalle_has_no_comma(self):
        bridge = FakeBridge()
        self._patch_bridge(bridge)
        await _run(TakPublishPipeline(), _msg(_7S_NO_COMMA))
        self.assertEqual(len(bridge.published), 1)

    async def test_no_coords_warns_and_does_not_publish(self):
        bridge = FakeBridge()
        self._patch_bridge(bridge)
        pipeline = TakPublishPipeline()
        await _run(pipeline, _msg(_7S_NO_COORDS))
        self.assertEqual(bridge.published, [])
        self.assertTrue(any(w["field"] == "stalle" for w in pipeline.last_warnings))

    async def test_ignores_non_7s(self):
        bridge = FakeBridge()
        self._patch_bridge(bridge)
        await _run(TakPublishPipeline(), _msg("Lägesrapport\nTill: A"))
        self.assertEqual(bridge.published, [])

    async def test_ignores_own_tak_echo(self):
        bridge = FakeBridge()
        self._patch_bridge(bridge)
        await _run(TakPublishPipeline(), _msg(_7S_WITH_COORDS, source="tak"))
        self.assertEqual(bridge.published, [])

    async def test_noop_when_bridge_down(self):
        self._patch_bridge(FakeBridge(running=False))
        self.assertFalse(await _run(TakPublishPipeline(), _msg(_7S_WITH_COORDS)))

    async def test_noop_when_no_bridge(self):
        self._patch_bridge(None)
        self.assertFalse(await _run(TakPublishPipeline(), _msg(_7S_WITH_COORDS)))


if __name__ == "__main__":
    unittest.main()
