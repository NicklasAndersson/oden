"""
Responses table CRUD for Oden's SQLite config database.

Manages command auto-reply responses (e.g. #help, #ok).
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from oden.config_db import init_db

logger = logging.getLogger(__name__)

_DEFAULT_HELP_BODY = """\
Stund
Ställe
Styrka
Slag
Sysselsättning
Symbol
Sagesman
Sedan

---
**Hur gör man**
Det går bra att skicka bilder och använda signals platsdelning. Sträva efter att skicka allt i ett meddelande eller svara på den ursprungliga rapporten.

Undvik att diskutera i den här kanalen. Om du absolut måste kommentera, använd -- prefixet för att undvika att ditt meddelande sparas i rapporten.
**Speciella kommandon:**
- **Svara på meddelanden:** Om du svarar på ett meddelande (inom 30 minuter) läggs ditt svar till i din senaste rapport.
- `--`: Om du börjar ett meddelande med `--` ignoreras det och sparas inte."""

_DEFAULT_OK_BODY = "Mottaget."


def _seed_default_responses(cursor: sqlite3.Cursor) -> None:
    """Insert default responses into a fresh responses table."""
    cursor.execute(
        "INSERT INTO responses (keywords, body) VALUES (?, ?)",
        (json.dumps(["help", "hjälp"]), _DEFAULT_HELP_BODY),
    )
    cursor.execute(
        "INSERT INTO responses (keywords, body) VALUES (?, ?)",
        (json.dumps(["ok"]), _DEFAULT_OK_BODY),
    )
    logger.info("Seeded default responses into database")


def get_all_responses(db_path: Path) -> list[dict[str, Any]]:
    """Return all responses as a list of dicts with id, keywords (list), and body."""
    if not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, keywords, body FROM responses ORDER BY id")
        return [{"id": row[0], "keywords": json.loads(row[1]), "body": row[2]} for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Error reading responses: {e}")
        return []
    finally:
        conn.close()


def get_response_by_keyword(db_path: Path, keyword: str) -> str | None:
    """Look up a response body by keyword (case-insensitive, uses json_each)."""
    if not db_path.exists():
        return None

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT body FROM responses, json_each(responses.keywords) WHERE LOWER(json_each.value) = ? LIMIT 1",
            (keyword.lower(),),
        )
        row = cursor.fetchone()
        return row[0] if row else None
    except sqlite3.Error as e:
        logger.error(f"Error looking up response for keyword '{keyword}': {e}")
        return None
    finally:
        conn.close()


def get_response_by_id(db_path: Path, response_id: int) -> dict[str, Any] | None:
    """Return a single response by its id."""
    if not db_path.exists():
        return None

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, keywords, body FROM responses WHERE id = ?", (response_id,))
        row = cursor.fetchone()
        if row:
            return {"id": row[0], "keywords": json.loads(row[1]), "body": row[2]}
        return None
    except sqlite3.Error as e:
        logger.error(f"Error reading response id={response_id}: {e}")
        return None
    finally:
        conn.close()


def create_response(db_path: Path, keywords: list[str], body: str) -> int | None:
    """Create a new response. Keywords are normalized to lowercase. Returns the new id."""
    if not db_path.exists():
        init_db(db_path)

    normalized = [k.strip().lower() for k in keywords if k.strip()]
    if not normalized:
        return None

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO responses (keywords, body) VALUES (?, ?)",
            (json.dumps(normalized, ensure_ascii=False), body),
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        logger.error(f"Error creating response: {e}")
        return None
    finally:
        conn.close()


def save_response(db_path: Path, response_id: int, keywords: list[str], body: str) -> bool:
    """Update an existing response. Keywords are normalized to lowercase."""
    if not db_path.exists():
        return False

    normalized = [k.strip().lower() for k in keywords if k.strip()]
    if not normalized:
        return False

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE responses SET keywords = ?, body = ? WHERE id = ?",
            (json.dumps(normalized, ensure_ascii=False), body, response_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Error saving response id={response_id}: {e}")
        return False
    finally:
        conn.close()


def delete_response(db_path: Path, response_id: int) -> bool:
    """Delete a response by id."""
    if not db_path.exists():
        return False

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM responses WHERE id = ?", (response_id,))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Error deleting response id={response_id}: {e}")
        return False
    finally:
        conn.close()
