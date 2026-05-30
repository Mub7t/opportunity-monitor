"""
similarity.py — Project Similarity Detection

Before notifying about a project, compares it against the project history
in the SQLite database. Uses TF-IDF-style token overlap (no heavy ML deps)
to find similar past projects and detect repeated client needs / trends.

Returns:
  similarity_score    : 0.0–1.0
  similar_projects    : list of {id, title, score, discovered_at}
  related_categories  : list of repeated categories
  trend_note          : optional observation about patterns
"""

import logging
import re
from collections import Counter

log = logging.getLogger(__name__)


# ─── Text normalization ───────────────────────────────────────────────────────

_STOP_WORDS = {
    "على", "في", "من", "إلى", "عن", "مع", "هذا", "هذه", "ذلك", "تلك",
    "التي", "الذي", "وال", "كان", "يكون", "أن", "إن", "لا", "ما", "لم",
    "هل", "قد", "كل", "بعد", "قبل", "حتى", "أو", "و", "ب", "ل", "ك",
    "project", "work", "need", "want", "looking", "for", "with", "the", "and",
    "مشروع", "مطلوب", "أحتاج", "تصميم", "عمل", "خدمة", "خدمات",
}


def _tokenize(text: str) -> Counter:
    """Normalize Arabic/English text into a token frequency counter."""
    text = text.lower()
    # Remove URLs, numbers, punctuation
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\d+", "", text)
    text = re.sub(r"[^\w\s\u0600-\u06ff]", " ", text)
    tokens = [t for t in text.split() if len(t) > 2 and t not in _STOP_WORDS]
    return Counter(tokens)


def _jaccard_similarity(a: Counter, b: Counter) -> float:
    """Compute Jaccard similarity between two token counters."""
    if not a or not b:
        return 0.0
    set_a = set(a.keys())
    set_b = set(b.keys())
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _cosine_like(a: Counter, b: Counter) -> float:
    """Lightweight cosine similarity (no numpy)."""
    if not a or not b:
        return 0.0
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    mag_a = sum(v * v for v in a.values()) ** 0.5
    mag_b = sum(v * v for v in b.values()) ** 0.5
    return dot / (mag_a * mag_b) if mag_a > 0 and mag_b > 0 else 0.0


def _project_text(p: dict) -> str:
    """Build a single text string from a project dict (raw or DB row)."""
    return " ".join(filter(None, [
        p.get("title", ""),
        p.get("description", ""),
        p.get("category", ""),
        p.get("raw_text", ""),
    ]))


# ─── Main similarity function ─────────────────────────────────────────────────

def find_similar_projects(
    project: dict,
    history: list[dict],
    threshold: float = 0.45,
    top_n: int = 5,
) -> dict:
    """
    Compare project against historical projects.

    Args:
        project    : the new project dict
        history    : list of past project dicts (from database.get_all_projects)
        threshold  : minimum similarity score to include in results
        top_n      : max results to return

    Returns:
        similar_projects   : list of {id, title, similarity, discovered_at, category}
        max_similarity     : highest similarity found (0.0–1.0)
        related_categories : categories that appear repeatedly
        trend_note         : text observation if a pattern is detected
    """
    if not history:
        return {
            "similar_projects":   [],
            "max_similarity":     0.0,
            "related_categories": [],
            "trend_note":         "",
        }

    new_tokens = _tokenize(_project_text(project))
    results    = []

    for past in history:
        past_text   = _project_text(past)
        past_tokens = _tokenize(past_text)

        # Use average of Jaccard + cosine for robustness
        jacc = _jaccard_similarity(new_tokens, past_tokens)
        cosine = _cosine_like(new_tokens, past_tokens)
        score = (jacc + cosine) / 2.0

        if score >= threshold:
            results.append({
                "id":           past.get("id", ""),
                "title":        past.get("title", ""),
                "similarity":   round(score, 3),
                "discovered_at": past.get("discovered_at", ""),
                "category":     past.get("category", ""),
                "url":          past.get("url", ""),
            })

    results.sort(key=lambda x: -x["similarity"])
    results = results[:top_n]

    max_sim = results[0]["similarity"] if results else 0.0

    # Find repeated categories among similar results
    cat_counts: Counter = Counter(r["category"] for r in results if r["category"])
    related_cats = [cat for cat, cnt in cat_counts.most_common(3) if cnt >= 1]

    # Trend note
    trend_note = ""
    if len(results) >= 3:
        trend_note = f"هذا النوع من المشاريع ({related_cats[0] if related_cats else 'غير محدد'}) يظهر بشكل متكرر — قد يكون عميلاً متكرراً أو حاجة سوقية متزايدة."
    elif len(results) == 1:
        trend_note = f"مشروع مشابه سبق اكتشافه."

    log.debug(
        "Similarity for '%s': max=%.2f, found=%d similar",
        project.get("title", "")[:40], max_sim, len(results)
    )

    return {
        "similar_projects":   results,
        "max_similarity":     max_sim,
        "related_categories": related_cats,
        "trend_note":         trend_note,
    }
