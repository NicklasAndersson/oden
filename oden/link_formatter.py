"""
Link formatting for Signal message content.

Applies regex patterns to text and converts matches to Obsidian-style links.
"""

import logging
import re

from oden import config as cfg

logger = logging.getLogger(__name__)


def apply_regex_links(text: str | None) -> str | None:
    """
    Applies regex patterns from configuration to text and converts matches to [[...]] links.
    Avoids linking text that is already inside [[...]].
    """
    if not text or not cfg.REGEX_PATTERNS:
        return text

    # Find all existing [[...]] patterns to avoid double-linking
    existing_links = set(re.findall(r"\[\[([^\]]+)\]\]", text))

    for pattern_name, pattern in cfg.REGEX_PATTERNS.items():
        try:
            # Find all matches
            matches = re.finditer(pattern, text)
            for match in matches:
                matched_text = match.group(0)
                # Only link if it's not already in an existing link
                if matched_text not in existing_links:
                    text = text.replace(matched_text, f"[[{matched_text}]]", 1)
                    existing_links.add(matched_text)
        except Exception as e:
            logger.warning(f"Error applying regex pattern '{pattern_name}': {e}")

    return text
