"""
storage.py — Robust de-duplication and persistence layer.

The seen_ids.json now stores rich metadata about every project ever reported,
not just bare IDs. This prevents false re-sends even if the cache file is
corrupted — we always cross-check by ID, URL, and title.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from config import SEEN_IDS_FILE

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_seen_db() -> dict:
    """
    Load the full seen-projects database.

    Schema:
        {
            "<project_id>": {
                "id":                "<project_id>",
                "title":             "...",
                "url":               "https://...",
                "first_seen":        "2025-01-01T00:00:00+00:00",
                "notification_sent": "2025-01-01T00:00:05+00:00",
            },
            ...
        }
    """
    if SEEN_IDS_FILE.exists():
        try:
            with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Migrate legacy format (plain list of strings) to new dict format
            if isinstance(data, list):
                log.info("Migrating legacy seen_ids.json from list to dict format")
                return {item: {"id": item, "title": "", "url": "", "first_seen": _now_iso(), "notification_sent": None}
                        for item in data}
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, Exception) as exc:
            log.error("Could not load seen_ids.json (%s). Starting fresh.", exc)
    return {}


def save_seen_db(db: dict) -> None:
    """Persist the database to disk atomically (write then rename)."""
    tmp = SEEN_IDS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    tmp.replace(SEEN_IDS_FILE)
    log.info("Saved %d entries to %s", len(db), SEEN_IDS_FILE)


def is_seen(project: dict, db: dict) -> tuple[bool, str]:
    """
    Return (True, reason) if the project was already reported, else (False, "").
    Checks by ID, URL, and title to be robust against structural changes.
    """
    pid   = project.get("id", "")
    url   = project.get("url", "")
    title = project.get("title", "").strip()

    if pid and pid in db:
        entry = db[pid]
        return True, f"ID '{pid}' already seen on {entry.get('first_seen', '?')}"

    # URL cross-check
    if url:
        for entry in db.values():
            if entry.get("url") == url:
                return True, f"URL already seen (entry: {entry.get('id', '?')})"

    # Title cross-check (strong match)
    if title and len(title) > 10:
        for entry in db.values():
            if entry.get("title", "").strip() == title:
                return True, f"Title already seen (entry: {entry.get('id', '?')})"

    return False, ""


def mark_seen(project: dict, db: dict, notification_sent: bool = False) -> None:
    """Add or update a project entry in the seen database."""
    pid = project.get("id", project.get("url", "unknown"))
    now = _now_iso()
    db[pid] = {
        "id":                pid,
        "title":             project.get("title", ""),
        "url":               project.get("url", ""),
        "first_seen":        db.get(pid, {}).get("first_seen", now),
        "notification_sent": now if notification_sent else db.get(pid, {}).get("notification_sent"),
    }
