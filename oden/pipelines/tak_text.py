"""TAK → text: the pre-step that turns a received CoT into the text later steps read.

TAK sends XML (CoT), not text. The listener already makes text of it at receipt
(8S → ``7S RAPPORT``, SCRIM → ``SCRIM RAPPORT``, anything else a
``TAK-OBSERVATION`` note) and stores the raw XML alongside (``_cot_xml``). This
step redoes that conversion from the stored XML with the branch's settings, so
the conversion is a visible step in Flöde with a reason, and can be changed
without code:

* ``reshape_8s`` / ``reshape_scrim``: reshape the form, or keep it as an observation
* ``other``: ``observation`` (default) or ``skip`` — a skipped marker is only kept
  in Flöde (status ignored) and nothing is written
* ``raw_block``: keep the form verbatim in a trailing ``%% … %%`` block

It writes nothing itself. The orchestrator hands the new text to the steps
after it (``last_transformed``); with default settings that text is exactly the
text stored at receipt. Messages not from TAK pass through untouched.
"""

from __future__ import annotations

import copy
from typing import Any

from oden import config as cfg
from oden.messages_db import STATUS_IGNORED, STATUS_PROCESSED
from oden.routing import step_settings


class TakTextPipeline:
    name = "tak_text"
    display_name = "TAK → text"
    description = "Gör om ett meddelande från TAK (CoT/XML) till text som stegen efter läser."
    selection_criteria = "Körs för meddelanden från TAK. Signal-meddelanden går vidare orörda."

    def __init__(self) -> None:
        self.status_on_handle = STATUS_PROCESSED
        self.last_reason: str | None = None
        self.last_transformed: dict[str, Any] | None = None

    def settings(self) -> dict[str, Any]:
        from oden.tak.listener import TEXT_DEFAULTS

        configured = step_settings(self.name, cfg.PIPELINE_SETTINGS)
        return {key: configured.get(key, default) for key, default in TEXT_DEFAULTS.items()}

    async def run(self, *, msg_data: dict[str, Any], reader: Any, writer: Any) -> bool:
        del reader, writer
        return self.convert(msg_data)

    def convert(self, msg_data: dict[str, Any]) -> bool:
        """True only when the marker is to be skipped (the step then takes it, status ignored)."""
        from oden.tak.cot import cot_to_inbound
        from oden.tak.listener import render_message

        self.status_on_handle = STATUS_PROCESSED
        self.last_transformed = None
        envelope = msg_data.get("envelope") or {}
        if envelope.get("_source") != "tak":
            self.last_reason = "Inte från TAK – går vidare orört"
            return False
        xml = envelope.get("_cot_xml")
        if not xml:
            self.last_reason = "Ingen rå CoT sparad (mottaget före försteget) – texten från mottagningen används"
            return False
        cot = cot_to_inbound(xml)
        if cot is None:
            raise ValueError("Den sparade CoT:en gick inte att tolka")

        text, what = render_message(cot, self.settings())
        if text is None:
            self.status_on_handle = STATUS_IGNORED
            self.last_reason = what
            return True

        transformed = copy.deepcopy(msg_data)
        transformed["envelope"].setdefault("dataMessage", {})["message"] = text
        self.last_transformed = transformed
        self.last_reason = what
        return False
