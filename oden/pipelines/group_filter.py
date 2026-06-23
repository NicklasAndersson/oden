"""Pipeline that filters messages based on configured Signal groups."""

from __future__ import annotations

import logging
from typing import Any

from oden import config as cfg
from oden.messages_db import STATUS_IGNORED
from oden.pipeline_settings import is_group_filtered

logger = logging.getLogger(__name__)


class GroupFilterPipeline:
    """Filter messages by group name using pipeline-specific settings."""

    name = "group_filter"
    display_name = "Gruppfilter-pipeline"
    description = "Filtrerar bort grupper enligt pipeline-inställningar (blacklist/whitelist)."
    selection_criteria = "Körs först och stoppar flödet om gruppen matchar filterregeln."
    status_on_handle = STATUS_IGNORED

    async def run(
        self,
        *,
        msg_data: dict[str, Any],
        reader: Any,
        writer: Any,
    ) -> bool:
        del reader, writer

        envelope = msg_data.get("envelope", {})
        if not envelope:
            return False

        dm = envelope.get("dataMessage") or {}
        group_meta = dm.get("groupV2") or dm.get("group") or dm.get("groupInfo") or {}
        group_title = group_meta.get("name") or group_meta.get("title") or group_meta.get("groupName")

        if is_group_filtered(group_title, cfg.PIPELINE_SETTINGS):
            logger.info("Message filtered by group_filter pipeline: %s", group_title)
            return True

        return False
