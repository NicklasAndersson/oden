import os
import re
import datetime
from typing import Optional, Dict, Any, List
from oden.config import VAULT_PATH

# ==============================================================================
# FILENAME AND CONTENT FORMATTING
# ==============================================================================

def get_safe_group_dir_path(group_title: str) -> str:
    """Sanitizes a group title and returns the full path for the group's directory."""
    safe_title = re.sub(r'[^\w\-_\. ]', '_', group_title)
    return os.path.join(VAULT_PATH, safe_title)


def _format_phone_number(number_str: Optional[str]) -> Optional[str]:
    """Säkerställer att ett telefonnummer formateras med prefixet 'tel-'."""
    if not number_str:
        return None
    return f" [[{number_str}]]"


def create_message_filename(dt: datetime.datetime, source_name: Optional[str], source_number: Optional[str]) -> str:
    """Creates a sanitized, timestamped filename for a message."""
    ts_str = dt.strftime("%d%H%M")
    parts = []
    if source_number:
        parts.append(source_number.lstrip('+'))
    if source_name:
        parts.append(source_name)
    
    if not parts:
        parts.append("unknown")

    safe_source = re.sub(r'[^\w\-_\.]', '_', "-".join(parts))
    return f"{ts_str}-{safe_source}.md"


def format_sender_display(source_name: Optional[str], source_number: Optional[str]) -> str:
    """Constructs a display string for the sender, including name and number."""
    formatted_number = _format_phone_number(source_number)
    if source_name and source_number:
        return f"{source_name} ({formatted_number})"
    return source_name or formatted_number or "Okänd"


def get_message_filepath(group_title: str, dt: datetime.datetime, source_name: Optional[str], source_number: Optional[str]) -> str:
    """Constructs the full, safe path for a new message file."""
    group_dir = get_safe_group_dir_path(group_title)
    filename = create_message_filename(dt, source_name, source_number)
    return os.path.join(group_dir, filename)


def _format_quote(quote: Dict[str, Any]) -> List[str]:
    """Formats a quote block into a markdown blockquote."""
    author_name = quote.get("authorName")
    author_number = quote.get("authorNumber")
    author_display = format_sender_display(author_name, author_number)
    text = quote.get("text", "...")

    # Indent every line of the quoted text for markdown blockquote
    quoted_lines = [f"> {line}" for line in text.split('\n')]
    
    return [
        f"> **Svarar på {author_display}:**",
        *quoted_lines
    ]
