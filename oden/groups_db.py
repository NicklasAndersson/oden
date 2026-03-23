"""
Groups table CRUD for Oden's SQLite config database.

Manages Signal group persistence for restart recovery and web GUI display.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from oden.config_db import init_db

logger = logging.getLogger(__name__)


def upsert_group(
    db_path: Path,
    group_id: str,
    name: str,
    member_count: int = 0,
    is_member: bool = True,
) -> bool:
    """Insert or update a group in the database."""
    if not db_path.exists():
        init_db(db_path)

    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO groups (group_id, name, member_count, is_member, last_seen) VALUES (?, ?, ?, ?, ?)",
            (group_id, name, member_count, 1 if is_member else 0, now),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error("Error upserting group '%s': %s", name, e)
        return False
    finally:
        conn.close()


def upsert_groups_bulk(db_path: Path, groups: list[dict]) -> int:
    """Bulk upsert a list of group dicts (as returned by listGroups).

    Returns the number of groups written.
    """
    if not groups:
        return 0
    if not db_path.exists():
        init_db(db_path)

    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        rows = [
            (
                g.get("id", ""),
                g.get("name", "Okänd grupp"),
                len(g.get("members", [])),
                1 if g.get("isMember", True) else 0,
                now,
            )
            for g in groups
            if g.get("id")
        ]
        cursor.executemany(
            "INSERT OR REPLACE INTO groups (group_id, name, member_count, is_member, last_seen) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return len(rows)
    except sqlite3.Error as e:
        logger.error("Error bulk-upserting groups: %s", e)
        return 0
    finally:
        conn.close()


def get_all_groups(db_path: Path) -> list[dict]:
    """Return all groups stored in the database."""
    if not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT group_id, name, member_count, is_member, last_seen FROM groups ORDER BY name")
        return [
            {
                "id": row[0],
                "name": row[1],
                "memberCount": row[2],
                "isMember": bool(row[3]),
                "lastSeen": row[4],
            }
            for row in cursor.fetchall()
        ]
    except sqlite3.Error as e:
        logger.error("Error reading groups: %s", e)
        return []
    finally:
        conn.close()


def delete_group(db_path: Path, group_id: str) -> bool:
    """Delete a group by id."""
    if not db_path.exists():
        return False

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Error deleting group '%s': %s", group_id, e)
        return False
    finally:
        conn.close()
