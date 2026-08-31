"""
Contacts table CRUD for Oden's SQLite config database.

Manages Signal contact persistence for restart recovery, mirroring groups_db.py.
Each contact is stored as its raw signal-cli dict (JSON) so no fields are lost.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from oden.config_db import init_db

logger = logging.getLogger(__name__)


def upsert_contacts_bulk(db_path: Path, contacts: list[dict], account: str = "") -> int:
    """Bulk upsert a list of contact dicts (as returned by listContacts).

    Returns the number of contacts written.
    """
    if not contacts:
        return 0
    if not db_path.exists():
        init_db(db_path)

    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        rows = [(c["number"], account, json.dumps(c), now) for c in contacts if c.get("number")]
        cursor.executemany(
            "INSERT OR REPLACE INTO contacts (number, account, data, last_seen) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return len(rows)
    except sqlite3.Error as e:
        logger.error("Error bulk-upserting contacts: %s", e)
        return 0
    finally:
        conn.close()


def get_all_contacts(db_path: Path, account: str | None = None) -> list[dict]:
    """Return contacts stored in the database, as their raw signal-cli dicts.

    If *account* is given, only contacts belonging to that account are returned.
    """
    if not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if account is not None:
            cursor.execute("SELECT data FROM contacts WHERE account = ?", (account,))
        else:
            cursor.execute("SELECT data FROM contacts")
        return [json.loads(row[0]) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error("Error reading contacts: %s", e)
        return []
    finally:
        conn.close()
