"""
win_probability.py — Real Win Probability Engine (v3)

Moves beyond pure AI guessing. Uses a weighted formula that factors in:
  1. Number of existing proposals (fewer = better odds for you)
  2. Project age in minutes (newer = better odds — apply fast)
  3. Profile match strength (how well Mubarak's skills fit)
  4. Budget attractiveness (moderate budgets → more serious clients)
  5. AI quality estimate (minor component, sanity-check only)

Returns:
  probability   : 0–100 integer (realistic win %)
  confidence    : low | medium | high
  explanation   : Arabic explanation of the estimate
  breakdown     : dict of individual component scores for transparency
"""

import logging
import re
from datetime import datetime, timezone

from config import WIN_PROB_WEIGHTS, SKILL_DOMAINS

log = logging.getLogger(__name__)

# ─── Component scorers ────────────────────────────────────────────────────────

def _score_proposal_count(raw_text: str) -> tuple[float, str]:
    """
    Fewer existing proposals = higher win chance.
    Extract proposal count from raw card text.
    Returns (score 0-1, explanation).
    """
    # Common Arabic patterns on bahr.sa cards
    patterns = [
        r"(\d+)\s*عروض?",
        r"(\d+)\s*proposal",
        r"(\d+)\s*مقترح",
        r"(\d+)\s*offer",
        r"(\d+)\s*بيد",
    ]
    count = None
    for pat in patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            count = int(m.group(1))
            break

    if count is None:
        # Cannot determine — assume medium competition
        return 0.5, "عدد العروض غير محدد (تنافس متوسط)"

    if count == 0:
        return 1.0, f"لا توجد عروض بعد — فرصة ممتازة للتقديم أولاً"
    if count <= 3:
        return 0.85, f"{count} عروض فقط — منافسة منخفضة جداً"
    if count <= 7:
        return 0.65, f"{count} عروض — منافسة معتدلة"
    if count <= 15:
        return 0.40, f"{count} عروض — منافسة مرتفعة"
    if count <= 30:
        return 0.20, f"{count} عرضاً — منافسة عالية جداً"
    return 0.08, f"{count}+ عرضاً — منافسة شديدة"


def _score_project_age(raw_text: str, discovered_at: str | None = None) -> tuple[float, str]:
    """
    Newer projects = higher win chance (apply early wins more bids).
    Tries to extract relative age from card text, falls back to discovery time.
    """
    # Arabic relative time patterns
    just_posted = [
        r"منذ\s+دقيق", r"منذ\s+ثانية", r"الآن", r"just now", r"seconds ago",
        r"منذ\s+\d+\s+دقيق",
    ]
    recent = [
        r"منذ\s+[1-9]\s+ساع", r"منذ\s+ساع", r"hour[s]? ago", r"منذ\s+نصف ساع",
    ]
    today_ish = [
        r"منذ\s+(1[0-9]|2[0-4])\s+ساع", r"اليوم", r"today",
    ]
    day_old = [r"أمس", r"yesterday", r"منذ\s+يوم", r"منذ\s+\d+\s+أيام?"]

    text_lower = raw_text.lower()
    for pat in just_posted:
        if re.search(pat, text_lower):
            return 1.0, "نُشر للتو — تقديم فوري مفيد جداً"
    for pat in recent:
        if re.search(pat, text_lower):
            return 0.85, "نُشر منذ ساعات — لا تزال الفرصة جيدة"
    for pat in today_ish:
        if re.search(pat, text_lower):
            return 0.70, "نُشر اليوم — فرصة جيدة"
    for pat in day_old:
        if re.search(pat, text_lower):
            return 0.45, "نُشر منذ يوم أو أكثر — معقول"

    # Fallback to discovery time
    if discovered_at:
        try:
            dt = datetime.fromisoformat(discovered_at)
            age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            if age_hours < 2:
                return 0.90, "اكتُشف حديثاً — فرصة جيدة"
            if age_hours < 12:
                return 0.70, "اكتُشف اليوم"
            if age_hours < 48:
                return 0.45, "يوم أو يومان"
            return 0.25, "قديم نسبياً"
        except Exception:
            pass

    return 0.55, "عمر المشروع غير محدد"


def _score_profile_match(raw_text: str, title: str) -> tuple[float, str]:
    """
    How well does this project match Mubarak's skill domains?
    Uses the weighted SKILL_DOMAINS map.
    """
    haystack = (title + " " + raw_text).lower()
    total_weight = 0.0
    matched_domains = []

    for domain, weight in SKILL_DOMAINS.items():
        if domain.lower() in haystack:
            total_weight += weight
            matched_domains.append(domain)

    # Normalize: max possible is ~5.0 (if every top skill matches)
    # We cap at 1.0
    normalized = min(total_weight / 4.0, 1.0)

    if not matched_domains:
        return 0.20, "لا تطابق واضح مع مهاراتك"
    if normalized >= 0.75:
        return normalized, f"تطابق ممتاز: {', '.join(matched_domains[:3])}"
    if normalized >= 0.45:
        return normalized, f"تطابق جيد: {', '.join(matched_domains[:2])}"
    return normalized, f"تطابق جزئي: {matched_domains[0]}"


def _score_budget(raw_text: str) -> tuple[float, str]:
    """
    Parse budget from card text. Moderate budgets (500–5000 SAR) tend to
    come from more serious clients who follow through.
    """
    # Try to find a number with currency context
    patterns = [
        r"(\d[\d,\.]+)\s*(?:ريال|SAR|﷼|SR)",
        r"(?:ريال|SAR|﷼|SR)\s*(\d[\d,\.]+)",
        r"الميزانية[:\s]+(\d[\d,\.]+)",
        r"budget[:\s]+(\d[\d,\.]+)",
        r"\$\s*(\d[\d,\.]+)",
    ]
    budget = None
    for pat in patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            try:
                budget = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                continue

    if budget is None:
        return 0.5, "الميزانية غير محددة"

    if budget < 100:
        return 0.15, f"ميزانية منخفضة جداً ({budget:.0f} ريال) — قد لا يستحق"
    if budget < 500:
        return 0.35, f"ميزانية منخفضة ({budget:.0f} ريال)"
    if budget < 2000:
        return 0.70, f"ميزانية معقولة ({budget:.0f} ريال)"
    if budget < 8000:
        return 0.85, f"ميزانية جيدة ({budget:.0f} ريال)"
    if budget < 25000:
        return 0.80, f"ميزانية عالية ({budget:.0f} ريال) — عميل جاد"
    return 0.65, f"ميزانية ضخمة ({budget:.0f} ريال) — تنافس شديد غالباً"


def _score_ai_estimate(ai_win_chance: str) -> float:
    """Convert AI text estimate to a minor numeric component."""
    return {"low": 0.25, "medium": 0.55, "high": 0.82}.get(ai_win_chance, 0.50)


# ─── Confidence calculator ────────────────────────────────────────────────────

def _confidence(data_found: int) -> str:
    """
    How many data signals did we actually find?
    data_found counts how many components had real data (not defaults).
    """
    if data_found >= 4:
        return "high"
    if data_found >= 2:
        return "medium"
    return "low"


# ─── Main entry point ─────────────────────────────────────────────────────────

def compute_win_probability(project: dict, analysis: dict) -> dict:
    """
    Compute a realistic win probability for a project.

    Returns:
        probability   : 0–100 (int)
        confidence    : low | medium | high
        explanation   : Arabic explanation
        breakdown     : dict {component: score}
    """
    raw_text      = project.get("raw_text", "") + " " + project.get("description", "")
    title         = project.get("title", "")
    discovered_at = project.get("_discovered_at")   # injected by monitor.py if available

    # Score each component
    prop_score, prop_expl    = _score_proposal_count(raw_text)
    age_score, age_expl      = _score_project_age(raw_text, discovered_at)
    prof_score, prof_expl    = _score_profile_match(raw_text, title)
    budget_score, budget_expl = _score_budget(raw_text)
    ai_score = _score_ai_estimate(analysis.get("win_chance", "medium"))

    w = WIN_PROB_WEIGHTS
    raw_prob = (
        prop_score   * w["proposal_count"] +
        age_score    * w["project_age"]    +
        prof_score   * w["profile_match"]  +
        budget_score * w["budget_range"]   +
        ai_score     * w["ai_estimate"]
    )

    probability = round(raw_prob * 100)
    probability = max(3, min(95, probability))   # realistic bounds: never 0% or 100%

    # Count how many signals had real data (not defaults)
    data_signals = sum([
        prop_score != 0.5,     # 0.5 = default
        age_score  != 0.55,    # 0.55 = default
        budget_score != 0.5,   # 0.5 = default
        prof_score > 0.20,     # above "no match" floor
    ])

    confidence = _confidence(data_signals)

    # Build human-readable explanation
    explanation_parts = [
        f"• العروض الحالية: {prop_expl}",
        f"• عمر المشروع: {age_expl}",
        f"• تطابق المهارات: {prof_expl}",
        f"• الميزانية: {budget_expl}",
    ]
    explanation = "\n".join(explanation_parts)

    log.debug(
        "Win prob for '%s': %d%% (confidence=%s, signals=%d)",
        title[:40], probability, confidence, data_signals
    )

    return {
        "probability": probability,
        "confidence":  confidence,
        "explanation": explanation,
        "breakdown": {
            "proposal_count": round(prop_score * 100),
            "project_age":    round(age_score * 100),
            "profile_match":  round(prof_score * 100),
            "budget":         round(budget_score * 100),
            "ai_estimate":    round(ai_score * 100),
        },
    }
