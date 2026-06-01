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
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from config import SEEN_FINGERPRINTS_FILE

log = logging.getLogger(__name__)

WINDOW_DAYS = 7
TITLE_SIMILARITY_THRESHOLD = 0.85
TEXT_SIMILARITY_THRESHOLD = 0.80


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
    text = "".join(ch if not unicodedata.category(ch).startswith("S") else " " for ch in text)
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


def _source_independent_text(project: dict) -> str:
    return " ".join([
        _project_title(project),
        _project_description(project),
    ])


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def project_fingerprint(project: dict) -> str:
    normalized = normalize_text(_source_independent_text(project))
    return _hash_text(normalized)


def title_fingerprint(project: dict) -> str:
    return _hash_text(normalize_text(_project_title(project)))


def _title_tokens(normalized_title: str) -> list[str]:
    return [token for token in normalized_title.split() if len(token) > 1]


def _normalized_source_independent_text(project: dict) -> str:
    return normalize_text(_source_independent_text(project))


def _record_for(project: dict) -> dict:
    normalized_title = normalize_text(_project_title(project))
    normalized_description = normalize_text(_project_description(project))
    normalized_text = _normalized_source_independent_text(project)
    fingerprint = project_fingerprint(project)
    title_hash = _hash_text(normalized_title)
    return {
        "fingerprint": fingerprint,
        "title_fingerprint": title_hash,
        "source": project.get("source", ""),
        "url": project.get("url", ""),
        "title": _project_title(project),
        "normalized_title": normalized_title,
        "normalized_description": normalized_description,
        "normalized_text": normalized_text,
        "title_tokens": _title_tokens(normalized_title),
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
    log.info("Saved fingerprints: %d", len(pruned))
    log.info("Saved %d entries to %s", len(pruned), SEEN_FINGERPRINTS_FILE)


def _recent_records(db: dict) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    records = []
    for record in db.values():
        last_seen = _parse_dt(record.get("last_seen", "")) or _parse_dt(record.get("first_seen", ""))
        if last_seen and last_seen >= cutoff:
            records.append(record)
    return records


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    direct = SequenceMatcher(None, a, b).ratio()

    a_tokens = _title_tokens(a)
    b_tokens = _title_tokens(b)
    sorted_ratio = 0.0
    overlap = 0.0
    if a_tokens and b_tokens:
        sorted_ratio = SequenceMatcher(None, " ".join(sorted(a_tokens)), " ".join(sorted(b_tokens))).ratio()
        a_set = set(a_tokens)
        b_set = set(b_tokens)
        overlap = len(a_set & b_set) / max(len(a_set), len(b_set), 1)

    return max(direct, sorted_ratio, overlap)


def _text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    direct = SequenceMatcher(None, a, b).ratio()
    a_tokens = set(_title_tokens(a))
    b_tokens = set(_title_tokens(b))
    overlap = 0.0
    if a_tokens and b_tokens:
        overlap = len(a_tokens & b_tokens) / max(len(a_tokens), len(b_tokens), 1)
    return max(direct, overlap)


def duplicate_reason(project: dict, db: dict) -> tuple[str | None, dict | None]:
    fp = project_fingerprint(project)
    record = db.get(fp)
    if record in _recent_records(db):
        return "fingerprint", record

    url = str(project.get("url", "") or "").strip()
    normalized_title = normalize_text(_project_title(project))
    if not normalized_title:
        return None, None
    title_hash = _hash_text(normalized_title)
    normalized_text = _normalized_source_independent_text(project)

    for candidate in _recent_records(db):
        if candidate.get("fingerprint") == fp or candidate.get("title_fingerprint") == title_hash:
            return "fingerprint", candidate

        if url and candidate.get("url") == url:
            return "fingerprint", candidate

        candidate_title = candidate.get("normalized_title", "")
        if len(normalized_title) >= 10 and len(candidate_title) >= 10:
            similarity = _title_similarity(normalized_title, candidate_title)
            if similarity >= TITLE_SIMILARITY_THRESHOLD:
                candidate = dict(candidate)
                candidate["similarity"] = round(similarity, 3)
                return "similarity", candidate

        candidate_text = candidate.get("normalized_text") or normalize_text(
            str(candidate.get("normalized_title", "")) + " " +
            str(candidate.get("normalized_description", ""))
        )
        if len(normalized_text) < 20 or len(candidate_text) < 20:
            continue
        text_similarity = _text_similarity(normalized_text, candidate_text)
        if text_similarity >= TEXT_SIMILARITY_THRESHOLD:
            candidate = dict(candidate)
            candidate["similarity"] = round(text_similarity, 3)
            return "similarity", candidate

    return None, None


def remember_project(project: dict, db: dict) -> None:
    record = _record_for(project)
    existing = db.get(record["fingerprint"], {})
    if existing.get("first_seen"):
        record["first_seen"] = existing["first_seen"]
    db[record["fingerprint"]] = record


def remember_projects(projects: list[dict], db: dict) -> int:
    """Remember projects and return count of brand-new fingerprints created."""
    created = 0
    for project in projects:
        fp = project_fingerprint(project)
        if fp not in db:
            created += 1
        remember_project(project, db)
    return created


def filter_email_duplicates(enriched_projects: list[dict], db: dict) -> tuple[list[dict], dict]:
    kept = []
    stats = {"fingerprint": 0, "similarity": 0}
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
        if reason == "similarity":
            stats["similarity"] += 1
            log.info(
                "Skipped duplicate by similarity: [%s] %s ~ %s (%.0f%%)",
                project.get("source", ""),
                project.get("title", "")[:80],
                (matched or {}).get("title", "")[:80],
                float((matched or {}).get("similarity", 0)) * 100,
            )
            continue

        kept.append(ep)
        remember_project(project, working_db)

    return kept, stats


def filter_project_duplicates(projects: list[dict], db: dict) -> tuple[list[dict], dict]:
    """
    Filter raw projects against persisted 7-day fingerprints before expensive
    AI/ranking work. This does not add kept projects to the working DB, so
    cross-source matches from the same scrape can still be grouped for email.
    """
    kept = []
    stats = {"fingerprint": 0, "similarity": 0}
    for project in projects:
        reason, matched = duplicate_reason(project, db)
        if reason == "fingerprint":
            stats["fingerprint"] += 1
            log.info(
                "Skipped duplicate by fingerprint: [%s] %s",
                project.get("source", ""),
                project.get("title", "")[:80],
            )
            continue
        if reason == "similarity":
            stats["similarity"] += 1
            log.info(
                "Skipped duplicate by similarity: [%s] %s ~ %s (%.0f%%)",
                project.get("source", ""),
                project.get("title", "")[:80],
                (matched or {}).get("title", "")[:80],
                float((matched or {}).get("similarity", 0)) * 100,
            )
            continue
        kept.append(project)
    return kept, stats
