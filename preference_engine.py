"""
preference_engine.py — Personal Preference Learning System

Learns from user behavior over time:
  - Which categories they apply to
  - Which projects they ignore
  - Budget ranges they prefer
  - Categories they favorite / star

The learning data is persisted in preferences.json (lightweight) and the
SQLite preferences table (full history). The engine returns a 0–1 boost
factor that adjusts composite scoring based on past behavior.

Schema of preferences.json:
{
  "applied_projects":    ["id1", "id2", ...],
  "ignored_projects":    ["id3", ...],
  "starred_projects":    ["id4", ...],
  "favorite_categories": {"تصميم": 5, "برمجة": 3, ...},
  "ignored_categories":  {"ترجمة": 2, ...},
  "preferred_budgets":   {"500-2000": 4, "2000-8000": 6, ...},
  "high_scoring_projects": [{"id": ..., "score": ..., "category": ...}]
}
"""

import json
import logging
import re
from pathlib import Path

from config import PREFERENCES_FILE, SKILL_DOMAINS

log = logging.getLogger(__name__)

# ─── Load / save ──────────────────────────────────────────────────────────────

_DEFAULT_PREFS = {
    "applied_projects":     [],
    "ignored_projects":     [],
    "starred_projects":     [],
    "favorite_categories":  {},
    "ignored_categories":   {},
    "preferred_budgets":    {},
    "high_scoring_projects": [],
}


def load_preferences() -> dict:
    """Load preferences from disk. Returns defaults if file missing."""
    if PREFERENCES_FILE.exists():
        try:
            with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults to handle missing keys in older files
            merged = dict(_DEFAULT_PREFS)
            merged.update(data)
            return merged
        except Exception as exc:
            log.error("Could not load preferences.json: %s. Using defaults.", exc)
    return dict(_DEFAULT_PREFS)


def save_preferences(prefs: dict) -> None:
    """Persist preferences atomically."""
    tmp = PREFERENCES_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    tmp.replace(PREFERENCES_FILE)
    log.debug("Preferences saved.")


# ─── Learning signal recorders ────────────────────────────────────────────────

def record_applied(project_id: str, category: str, composite_score: float) -> None:
    """Call this when the user indicates they applied to a project."""
    prefs = load_preferences()
    if project_id not in prefs["applied_projects"]:
        prefs["applied_projects"].append(project_id)
    prefs["favorite_categories"][category] = prefs["favorite_categories"].get(category, 0) + 2
    # Remove from ignored if present
    if project_id in prefs["ignored_projects"]:
        prefs["ignored_projects"].remove(project_id)
    save_preferences(prefs)
    log.info("Preference: applied → %s (cat=%s)", project_id[:30], category)


def record_ignored(project_id: str, category: str) -> None:
    """Call this when the user marks a project as not relevant."""
    prefs = load_preferences()
    if project_id not in prefs["ignored_projects"]:
        prefs["ignored_projects"].append(project_id)
    prefs["ignored_categories"][category] = prefs["ignored_categories"].get(category, 0) + 1
    save_preferences(prefs)
    log.info("Preference: ignored → %s (cat=%s)", project_id[:30], category)


def record_starred(project_id: str, category: str) -> None:
    """Call this when the user stars/favorites a project."""
    prefs = load_preferences()
    if project_id not in prefs["starred_projects"]:
        prefs["starred_projects"].append(project_id)
    prefs["favorite_categories"][category] = prefs["favorite_categories"].get(category, 0) + 3
    save_preferences(prefs)


def auto_learn_from_high_scores(project: dict, composite_score: float, category: str) -> None:
    """
    Automatically treat high-scoring projects as implicit positive signals.
    Called by monitor.py for every project with composite_score >= 75.
    """
    prefs = load_preferences()
    pid = project.get("id", "")
    entry = {"id": pid, "score": composite_score, "category": category, "title": project.get("title", "")[:60]}

    # Keep last 200 high-scoring entries
    existing_ids = {e["id"] for e in prefs["high_scoring_projects"]}
    if pid not in existing_ids:
        prefs["high_scoring_projects"].append(entry)
        prefs["high_scoring_projects"] = prefs["high_scoring_projects"][-200:]

    # Mild boost to this category
    prefs["favorite_categories"][category] = prefs["favorite_categories"].get(category, 0) + 0.5
    save_preferences(prefs)


# ─── Preference boost calculator ─────────────────────────────────────────────

def _budget_bucket(raw_text: str) -> str | None:
    """Extract a budget bucket label from raw text."""
    patterns = [
        r"(\d[\d,]+)\s*(?:ريال|SAR|﷼|SR|\$)",
        r"(?:ريال|SAR|﷼|SR|\$)\s*(\d[\d,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if val < 500:
                    return "0-500"
                if val < 2000:
                    return "500-2000"
                if val < 8000:
                    return "2000-8000"
                if val < 25000:
                    return "8000-25000"
                return "25000+"
            except ValueError:
                pass
    return None


def compute_preference_boost(project: dict, category: str) -> float:
    """
    Return a preference boost factor in range 0.0–1.0.
    1.0 = strongly preferred category / budget.
    0.0 = strongly ignored.
    0.5 = neutral (no data yet).
    """
    prefs = load_preferences()
    pid   = project.get("id", "")

    # Hard blocks: explicitly ignored
    if pid in prefs["ignored_projects"]:
        return 0.05

    # Strong boost: applied or starred before (same project ID re-appeared, unlikely but safe)
    if pid in prefs["applied_projects"] or pid in prefs["starred_projects"]:
        return 0.95

    # Category signal
    fav_score = prefs["favorite_categories"].get(category, 0)
    ign_score = prefs["ignored_categories"].get(category, 0)
    net_cat   = fav_score - ign_score

    # Normalize net_cat: ±10 → ±0.4 boost/penalty on top of 0.5 neutral
    cat_factor = 0.5 + max(-0.4, min(0.4, net_cat * 0.04))

    # Budget signal
    bucket = _budget_bucket(project.get("raw_text", "") + project.get("description", ""))
    if bucket:
        bucket_hits = prefs["preferred_budgets"].get(bucket, 0)
        budget_factor = min(0.1, bucket_hits * 0.02)   # max +0.10
    else:
        budget_factor = 0.0

    boost = min(1.0, max(0.0, cat_factor + budget_factor))
    log.debug("Preference boost for '%s' (cat=%s): %.2f", project.get("title", "")[:30], category, boost)
    return boost


def record_budget_preference(raw_text: str) -> None:
    """Auto-call when user applies to record their budget bucket preference."""
    prefs = load_preferences()
    bucket = _budget_bucket(raw_text)
    if bucket:
        prefs["preferred_budgets"][bucket] = prefs["preferred_budgets"].get(bucket, 0) + 1
        save_preferences(prefs)


def get_preference_summary() -> str:
    """Return a human-readable summary for logging/debug."""
    prefs = load_preferences()
    fav  = sorted(prefs["favorite_categories"].items(), key=lambda x: -x[1])[:5]
    ign  = sorted(prefs["ignored_categories"].items(),  key=lambda x: -x[1])[:3]
    return (
        f"Applied: {len(prefs['applied_projects'])} | "
        f"Ignored: {len(prefs['ignored_projects'])} | "
        f"Fav cats: {fav} | "
        f"Ign cats: {ign}"
    )
