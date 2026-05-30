"""
profile_matcher.py — Professional Profile Matching for Mubarak

Scores how well a project matches Mubarak's specific skill domains using
the weighted SKILL_DOMAINS matrix from config. Returns a 0–100 match score
and explains which skills triggered the match.

This is separate from keyword filtering — it's about relevance depth,
not just presence.
"""

import logging
import re
from config import SKILL_DOMAINS, USER_PROFILE

log = logging.getLogger(__name__)

# ─── Domain categories for grouping ──────────────────────────────────────────

_DOMAIN_GROUPS = {
    "visual_production": ["تصوير", "فيديو", "مونتاج", "موشن جرافيك", "موشن",
                          "انتاج فيديو", "إنتاج فيديو", "تصوير فوتوغرافي"],
    "design":            ["تصميم", "جرافيك", "هوية بصرية", "تصميم جرافيك",
                          "هوية", "إعلان"],
    "digital_marketing": ["سوشال ميديا", "محتوى", "إعلان"],
    "web_development":   ["موقع", "تطوير ويب", "برمجة", "تطبيق", "متجر إلكتروني"],
    "ai_automation":     ["ذكاء اصطناعي", "أتمتة", "automation", "AI", "شات بوت"],
    "technical":         ["بايثون", "API", "تحليل بيانات", "استشارات"],
}

# Configurable per-group weight modifier (can be exposed as env vars later)
_GROUP_PRIORITY = {
    "visual_production": 1.0,
    "design":            1.0,
    "digital_marketing": 0.85,
    "web_development":   0.95,
    "ai_automation":     1.0,
    "technical":         0.90,
}


def compute_profile_match(project: dict) -> dict:
    """
    Compute a detailed profile match assessment.

    Returns:
        score           : 0–100 int
        matched_domains : list of matched skill names
        matched_groups  : list of triggered domain groups
        explanation     : Arabic explanation
        is_core_match   : True if any weight-1.0 domain matched
    """
    haystack = (
        project.get("title", "") + " " +
        project.get("description", "") + " " +
        project.get("raw_text", "")
    ).lower()

    matched_domains   = []
    matched_groups    = set()
    total_weight      = 0.0

    for domain, weight in SKILL_DOMAINS.items():
        if domain.lower() in haystack:
            matched_domains.append(domain)
            total_weight += weight
            # Find which group this domain belongs to
            for group, members in _DOMAIN_GROUPS.items():
                if domain in members:
                    matched_groups.add(group)
                    break

    # Apply group priority multipliers
    group_bonus = sum(_GROUP_PRIORITY.get(g, 1.0) for g in matched_groups) / max(len(matched_groups), 1)
    adjusted_weight = total_weight * min(group_bonus, 1.05)  # cap bonus at 5%

    # Normalize: sum of all weights at 1.0 ≈ 17; realistic max ≈ 5–6
    normalized = min(adjusted_weight / 5.0, 1.0)
    score = round(normalized * 100)

    # Is any core (weight=1.0) skill involved?
    is_core = any(SKILL_DOMAINS.get(d, 0) >= 0.95 for d in matched_domains)

    # Human explanation
    if not matched_domains:
        explanation = "لا يتطابق المشروع مع تخصصاتك الأساسية"
    elif score >= 80:
        explanation = f"تطابق ممتاز مع تخصصاتك: {', '.join(matched_domains[:4])}"
    elif score >= 55:
        explanation = f"تطابق جيد: {', '.join(matched_domains[:3])}"
    elif score >= 30:
        explanation = f"تطابق جزئي: {matched_domains[0]}"
    else:
        explanation = f"تطابق ضعيف: {matched_domains[0] if matched_domains else '—'}"

    log.debug(
        "Profile match for '%s': score=%d, groups=%s",
        project.get("title", "")[:40], score, list(matched_groups)
    )

    return {
        "score":            score,
        "matched_domains":  matched_domains,
        "matched_groups":   list(matched_groups),
        "explanation":      explanation,
        "is_core_match":    is_core,
    }


def profile_relevance_score(project: dict) -> float:
    """Convenience: return 0.0–1.0 normalized score for use in composite scoring."""
    return compute_profile_match(project)["score"] / 100.0
