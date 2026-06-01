"""
fingerprint_dedupe.py — 7-day email dedupe for similar opportunities.

This keeps the existing seen_ids.json behavior intact. It only controls whether
an already-ranked opportunity is allowed into the email report.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from config import SEEN_FINGERPRINTS_FILE

log = logging.getLogger(__name__)

WINDOW_DAYS = 7
FUZZY_THRESHOLD = 0.85


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def normalize_text(text: str) -> str:
    """Normalize Arabic/English text for stable duplicate detection."""
    text = str(text or "")
    text = text.lower()
    text = re.sub(r"[\U00010000-\U0010ffff]", " ", text)
    text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ة", "ه").replace("ى", "ي")
    text = re.sub(r"[^\w\s\u0600-\u06ff]", " ", text)
    text = re.sub(r"_+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _project_title(project: dict) -> str:
    return str(project.get("title", "") or "")


def _project_description(project: dict) -> str:
    return str(project.get("description", "") or project.get("raw_text", "") or "")


def project_fingerprint(project: dict) -> str:
    normalized = normalize_text(_project_title(project) + " " + _project_description(project))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _record_for(project: dict) -> dict:
    normalized_title = normalize_text(_project_title(project))
    normalized_description = normalize_text(_project_description(project))
    fingerprint = project_fingerprint(project)
    return {
        "fingerprint": fingerprint,
        "source": project.get("source", ""),
        "url": project.get("url", ""),
        "title": _project_title(project),
        "normalized_title": normalized_title,
        "normalized_description": normalized_description,
        "first_seen": _now_iso(),
        "last_seen": _now_iso(),
    }


def load_seen_fingerprints() -> dict:
    if not SEEN_FINGERPRINTS_FILE.exists():
        return {}
    try:
        with open(SEEN_FINGERPRINTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "fingerprints" in data:
            items = data.get("fingerprints", {})
            return items if isinstance(items, dict) else {}
        if isinstance(data, dict):
            return data
    except Exception as exc:
        log.warning("Could not load seen_fingerprints.json: %s", exc)
    return {}


def save_seen_fingerprints(db: dict) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    pruned = {}
    for fp, record in db.items():
        last_seen = _parse_dt(record.get("last_seen", "")) or _parse_dt(record.get("first_seen", ""))
        if last_seen and last_seen >= cutoff:
            pruned[fp] = record

    tmp = SEEN_FINGERPRINTS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)
    tmp.replace(SEEN_FINGERPRINTS_FILE)
    log.info("Saved %d entries to %s", len(pruned), SEEN_FINGERPRINTS_FILE)


def _recent_records(db: dict) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    records = []
    for record in db.values():
        last_seen = _parse_dt(record.get("last_seen", "")) or _parse_dt(record.get("first_seen", ""))
        if last_seen and last_seen >= cutoff:
            records.append(record)
    return records


def duplicate_reason(project: dict, db: dict) -> tuple[str | None, dict | None]:
    fp = project_fingerprint(project)
    record = db.get(fp)
    if record in _recent_records(db):
        return "fingerprint", record

    url = str(project.get("url", "") or "").strip()
    normalized_title = normalize_text(_project_title(project))
    if not normalized_title:
        return None, None

    for candidate in _recent_records(db):
        if url and candidate.get("url") == url:
            return "fingerprint", candidate

        candidate_title = candidate.get("normalized_title", "")
        if len(normalized_title) < 10 or len(candidate_title) < 10:
            continue
        similarity = SequenceMatcher(None, normalized_title, candidate_title).ratio()
        if similarity >= FUZZY_THRESHOLD:
            candidate = dict(candidate)
            candidate["similarity"] = round(similarity, 3)
            return "similar", candidate

    return None, None


def remember_project(project: dict, db: dict) -> None:
    record = _record_for(project)
    existing = db.get(record["fingerprint"], {})
    if existing.get("first_seen"):
        record["first_seen"] = existing["first_seen"]
    db[record["fingerprint"]] = record


def filter_email_duplicates(enriched_projects: list[dict], db: dict) -> tuple[list[dict], dict]:
    kept = []
    stats = {"fingerprint": 0, "similar": 0}
    working_db = dict(db)
    for ep in enriched_projects:
        project = ep.get("project", {})
        reason, matched = duplicate_reason(project, working_db)
        if reason == "fingerprint":
            stats["fingerprint"] += 1
            log.info(
                "Skipped duplicate by fingerprint: [%s] %s",
                project.get("source", ""),
                project.get("title", "")[:80],
            )
            continue
        if reason == "similar":
            stats["similar"] += 1
            log.info(
                "Skipped similar opportunity: [%s] %s ~ %s (%.0f%%)",
                project.get("source", ""),
                project.get("title", "")[:80],
                (matched or {}).get("title", "")[:80],
                float((matched or {}).get("similarity", 0)) * 100,
            )
            continue

        kept.append(ep)
        remember_project(project, working_db)

    return kept, stats
