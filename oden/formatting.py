import datetime
import logging
import os
import re
from typing import Any

from oden.config import APPEND_WINDOW_MINUTES, FILENAME_FORMAT, TIMEZONE, VAULT_PATH

logger = logging.getLogger(__name__)

# ==============================================================================
# FILENAME AND CONTENT FORMATTING
# ==============================================================================


def get_safe_group_dir_path(group_title: str) -> str:
    """Sanitizes a group title and returns the full path for the group's directory."""
    safe_title = re.sub(r"[^\w\-_\. ]", "_", group_title)
    return os.path.join(VAULT_PATH, safe_title)


def _format_phone_number(number_str: str | None) -> str | None:
    """Säkerställer att ett telefonnummer formateras med prefixet 'tel-'."""
    if not number_str:
        return None
    return f" [[{number_str}]]"


def create_fileid(dt: datetime.datetime, source_name: str | None, source_number: str | None) -> str:
    """
    Creates a unique file identifier (fileid) for a message.
    Format: TNR-phone-name (e.g., 261427-46762320406-Nicklas)
    This is used in frontmatter for consistent identification regardless of filename format.
    """
    tnr = dt.strftime("%d%H%M")
    parts = []
    if source_number:
        parts.append(source_number.lstrip("+"))
    if source_name:
        parts.append(source_name)

    if not parts:
        parts.append("unknown")

    safe_source = re.sub(r"[^\w\-_\.]", "_", "-".join(parts))
    return f"{tnr}-{safe_source}"


def create_message_filename(
    dt: datetime.datetime,
    source_name: str | None,
    source_number: str | None,
    filename_format: str | None = None,
) -> str:
    """
    Creates a sanitized, timestamped filename for a message.

    Args:
        dt: Message datetime
        source_name: Sender's name
        source_number: Sender's phone number
        filename_format: One of 'classic', 'tnr', or 'tnr-name'. Uses config if None.

    Returns:
        Filename string (without suffix for duplicates - use get_unique_filename for that)
    """
    if filename_format is None:
        filename_format = FILENAME_FORMAT

    tnr = dt.strftime("%d%H%M")

    if filename_format == "tnr":
        return f"{tnr}.md"

    if filename_format == "tnr-name":
        if source_name:
            safe_name = re.sub(r"[^\w\-_\.]", "_", source_name)
            return f"{tnr}-{safe_name}.md"
        else:
            return f"{tnr}.md"

    # Default: classic format (DDHHMM-phone-name.md)
    parts = []
    if source_number:
        parts.append(source_number.lstrip("+"))
    if source_name:
        parts.append(source_name)

    if not parts:
        parts.append("unknown")

    safe_source = re.sub(r"[^\w\-_\.]", "_", "-".join(parts))
    return f"{tnr}-{safe_source}.md"


def get_unique_filename(group_dir: str, base_filename: str) -> str:
    """
    Returns a unique filename by adding -1, -2, etc. suffix if file already exists.

    Args:
        group_dir: Directory path where file will be saved
        base_filename: Base filename (e.g., '261427.md' or '261427-Nicklas.md')

    Returns:
        Unique filename with suffix if needed (e.g., '261427-1.md' or '261427-Nicklas-1.md')
    """
    full_path = os.path.join(group_dir, base_filename)
    if not os.path.exists(full_path):
        return base_filename

    # Split filename to insert suffix before .md
    name_without_ext = base_filename[:-3]  # Remove '.md'

    # Find existing files with same base pattern
    counter = 1
    while True:
        new_filename = f"{name_without_ext}-{counter}.md"
        new_path = os.path.join(group_dir, new_filename)
        if not os.path.exists(new_path):
            return new_filename
        counter += 1


def _extract_fileid_from_file(filepath: str) -> str | None:
    """
    Extracts the fileid from a markdown file's frontmatter.

    Args:
        filepath: Path to the markdown file

    Returns:
        The fileid value if found, None otherwise
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read(1024)  # Read only first 1KB for efficiency

        # Check if file starts with frontmatter
        if not content.startswith("---"):
            return None

        # Find end of frontmatter
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return None

        frontmatter = content[3:end_idx]

        # Extract fileid
        match = re.search(r'^fileid:\s*["\']?([^"\'\n]+)["\']?\s*$', frontmatter, re.MULTILINE)
        if match:
            return match.group(1).strip()

        return None
    except Exception:
        return None


def find_latest_file_by_fileid(group_dir: str, source_name: str | None, source_number: str | None) -> str | None:
    """
    Finds the most recent file by a given sender in a group directory using fileid lookup.
    Returns the path to the most recent file within APPEND_WINDOW_MINUTES, or None.

    This searches for files where the fileid frontmatter property matches the sender's
    identifier pattern, enabling append mode to work across all filename formats.

    Args:
        group_dir: Directory to search
        source_name: Sender's name
        source_number: Sender's phone number

    Returns:
        Path to the most recent matching file, or None if not found within window
    """
    # Construct the fileid pattern to match (same logic as create_fileid but without TNR)
    sender_id_parts = []
    if source_number:
        sender_id_parts.append(source_number.lstrip("+"))
    if source_name:
        sender_id_parts.append(source_name)

    if not sender_id_parts:
        return None

    sender_pattern = re.sub(r"[^\w\-_\.]", "_", "-".join(sender_id_parts))

    latest_file = None
    latest_time = datetime.datetime.min.replace(tzinfo=TIMEZONE)
    now = datetime.datetime.now(TIMEZONE)

    try:
        candidate_files = [f for f in os.listdir(group_dir) if f.endswith(".md")]
    except FileNotFoundError:
        return None

    for filename in candidate_files:
        filepath = os.path.join(group_dir, filename)
        fileid = _extract_fileid_from_file(filepath)

        if not fileid:
            # Fallback: check if filename matches classic pattern for backwards compatibility
            if sender_pattern not in filename:
                continue
            # Extract timestamp from filename
            try:
                ts_str = filename.split("-")[0]
                if len(ts_str) != 6:
                    continue
            except (ValueError, IndexError):
                continue
        else:
            # Check if fileid contains the sender pattern
            if sender_pattern not in fileid:
                continue
            # Extract TNR from fileid (first 6 chars are DDHHMM)
            ts_str = fileid[:6]

        try:
            day = int(ts_str[0:2])
            hour = int(ts_str[2:4])
            minute = int(ts_str[4:6])

            if not (1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59):
                continue

            try:
                file_dt = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError:
                continue

            # Handle month rollover
            if file_dt > now:
                prev_month = now.month - 1 if now.month > 1 else 12
                prev_year = now.year if now.month > 1 else now.year - 1
                try:
                    file_dt = now.replace(
                        year=prev_year, month=prev_month, day=day, hour=hour, minute=minute, second=0, microsecond=0
                    )
                except ValueError:
                    continue
                if file_dt > now:
                    continue

            # Check if within append window
            time_diff = now - file_dt
            if time_diff < datetime.timedelta(minutes=APPEND_WINDOW_MINUTES) and (
                latest_file is None or file_dt > latest_time
            ):
                latest_time = file_dt
                latest_file = filepath
                logger.debug(f"Found candidate file: {filename} (age: {time_diff})")

        except (ValueError, IndexError) as e:
            logger.debug(f"Skipping file {filename}: {e}")
            continue

    if latest_file:
        logger.debug(f"Selected latest file for sender: {latest_file}")
    return latest_file


def format_sender_display(source_name: str | None, source_number: str | None) -> str:
    """Constructs a display string for the sender, including name and number."""
    formatted_number = _format_phone_number(source_number)
    if source_name and source_number:
        return f"{source_name} ({formatted_number})"
    return source_name or formatted_number or "Okänd"


def get_message_filepath(
    group_title: str,
    dt: datetime.datetime,
    source_name: str | None,
    source_number: str | None,
    unique: bool = True,
) -> str:
    """
    Constructs the full, safe path for a new message file.

    Args:
        group_title: Group name for directory
        dt: Message datetime
        source_name: Sender's name
        source_number: Sender's phone number
        unique: If True, ensures filename is unique by adding suffix if needed

    Returns:
        Full path to the message file
    """
    group_dir = get_safe_group_dir_path(group_title)
    filename = create_message_filename(dt, source_name, source_number)
    if unique:
        filename = get_unique_filename(group_dir, filename)
    return os.path.join(group_dir, filename)


def _format_quote(quote: dict[str, Any]) -> list[str]:
    """Formats a quote block into a markdown blockquote."""
    author_name = quote.get("authorName")
    author_number = quote.get("authorNumber")
    author_display = format_sender_display(author_name, author_number)
    text = quote.get("text", "...")

    # Indent every line of the quoted text for markdown blockquote
    quoted_lines = [f"> {line}" for line in text.split("\n")]

    return [f"> **Svarar på {author_display}:**", *quoted_lines]
