"""
scoring.py — Opportunity Monitor v1.1 personal scoring helpers.

This module is intentionally pure: it does not scrape, notify, write files, or
touch the seen_ids flow. It only adds scoring metadata and report-only smart
deduplication on top of the existing monitor pipeline.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone


SOURCE_LABELS = {
    "bahr": "Bahr",
    "mostaql": "Mostaql",
    "telegram": "Telegram",
}

PERSONAL_KEYWORDS: list[tuple[str, int]] = [
    ("تصوير زواج", 25),
    ("موشن جرافيك", 20),
    ("قناة أطفال", 15),
    ("هوية بصرية", 10),
    ("ذكاء اصطناعي", 15),
    ("Automation", 10),
    ("تصوير", 25),
    ("مصور", 25),
    ("مونتاج", 25),
    ("مونتير", 25),
    ("فيديو", 20),
    ("موشن", 20),
    ("ريلز", 15),
    ("يوتيوب", 15),
    ("درون", 20),
    ("Drone", 20),
    ("DJI", 15),
    ("فعالية", 20),
    ("تغطية", 20),
    ("تصميم", 10),
    ("AI", 15),
    ("موقع", 10),
    ("تطبيق", 10),
]

NEGATIVE_KEYWORDS: list[tuple[str, int]] = [
    ("المسمى الوظيفي", -80),
    ("دوام كامل", -80),
    ("دوام جزئي", -80),
    ("موارد بشرية", -50),
    ("مساعد إداري", -50),
    ("وظيفة", -80),
    ("وظيفي", -80),
    ("شاغر", -80),
    ("شاغرة", -80),
    ("راتب", -80),
    ("موظف", -80),
    ("موظفة", -80),
    ("محاسب", -50),
    ("سكرتير", -50),
]

SERIOUS_CLIENT_KEYWORDS: list[tuple[str, int]] = [
    ("جاهز للبدء", 10),
    ("ميزانية محددة", 10),
    ("يوجد سكربت", 10),
    ("يوجد محتوى جاهز", 10),
    ("مطلوب اليوم", 10),
    ("خلال 24 ساعة", 10),
    ("مشروع طويل", 10),
    ("مستعجل", 10),
    ("عقد", 10),
]

CATEGORY_KEYWORDS = {
    "تصوير": ["تصوير", "مصور", "درون", "drone", "dji", "فعالية", "تغطية"],
    "مونتاج": ["مونتاج", "مونتير", "فيديو", "موشن", "ريلز", "يوتيوب"],
    "تصميم": ["تصميم", "هوية بصرية", "جرافيك", "مصمم"],
    "AI": ["ai", "ذكاء اصطناعي", "automation", "أتمتة"],
    "برمجة": ["برمجة", "موقع", "تطبيق", "api", "بايثون", "python"],
}


def _project_text(project: dict) -> str:
    return " ".join([
        str(project.get("title", "")),
        str(project.get("description", "")),
        str(project.get("raw_text", "")),
        str(project.get("budget", "")),
    ])


def _contains(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def _to_western_digits(text: str) -> str:
    table = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return text.translate(table)


def _parse_budget(project: dict) -> tuple[float | None, str]:
    raw = " ".join([
        str(project.get("budget", "")),
        str(project.get("raw_text", "")),
        str(project.get("description", "")),
    ])
    text = _to_western_digits(raw)
    lowered = text.lower()

    numbers: list[float] = []
    for match in re.finditer(r"(?<!\w)(\d[\d,\.]{1,12})(?!\w)", text):
        number_text = match.group(1).replace(",", "")
        try:
            number = float(number_text)
        except ValueError:
            continue
        if 50 <= number <= 1_000_000:
            numbers.append(number)

    if "أقل من 500" in lowered or "اقل من 500" in lowered:
        return 499, "أقل من 500"
    if "أكثر من 5000" in lowered or "اكثر من 5000" in lowered:
        return 5001, "أكثر من 5000"
    if not numbers:
        return None, ""

    budget = max(numbers)
    return budget, f"{budget:,.0f}"


def _budget_score(project: dict) -> tuple[int, float | None, str]:
    budget, label = _parse_budget(project)
    if budget is None:
        return 0, None, ""
    if budget < 500:
        return 0, budget, label
    if budget <= 2000:
        return 10, budget, label
    if budget <= 5000:
        return 20, budget, label
    return 30, budget, label


def score_project(project: dict, base_score: float) -> dict:
    """Return v1.1 score details without mutating the project."""
    text = _project_text(project)
    matched_priority = [(kw, pts) for kw, pts in PERSONAL_KEYWORDS if _contains(text, kw)]
    matched_negative = [(kw, pts) for kw, pts in NEGATIVE_KEYWORDS if _contains(text, kw)]
    matched_serious = [(kw, pts) for kw, pts in SERIOUS_CLIENT_KEYWORDS if _contains(text, kw)]

    personal_score = sum(points for _, points in matched_priority)
    negative_score = sum(points for _, points in matched_negative)
    serious_score = sum(points for _, points in matched_serious)
    budget_score, budget_amount, budget_label = _budget_score(project)

    final_score = base_score + personal_score + budget_score + serious_score + negative_score
    has_job_post_signal = any(points <= -80 for _, points in matched_negative)
    excluded_from_email = has_job_post_signal or (negative_score <= -50 and final_score < 40)
    if excluded_from_email:
        final_score = 0

    final_score = round(max(0, min(100, final_score)), 1)

    reasons: list[str] = []
    if matched_priority:
        reasons.append(
            "اهتمامات قوية: " + "، ".join(f"{kw} +{points}" for kw, points in matched_priority[:6])
        )
    if budget_score:
        reasons.append(f"ميزانية مناسبة: {budget_label} +{budget_score}")
    if matched_serious:
        reasons.append(
            "إشارات جدية: " + "، ".join(f"{kw} +{points}" for kw, points in matched_serious[:4])
        )
    if matched_negative:
        reasons.append(
            "إشارات وظيفية/غير مناسبة: " + "، ".join(f"{kw} {points}" for kw, points in matched_negative[:4])
        )
    if not reasons:
        reasons.append("لا توجد إشارات إضافية قوية خارج التقييم الأساسي")

    if excluded_from_email or final_score < 45:
        recommendation = "❌ لا أنصح"
    elif final_score >= 85 and personal_score >= 25 and (budget_score >= 10 or serious_score >= 10):
        recommendation = "⭐ أوصي بشدة"
    elif final_score >= 70 and personal_score > 0:
        recommendation = "⭐ أوصي"
    else:
        recommendation = "⚠️ متوسط"

    return {
        "base_score": round(base_score, 1),
        "final_score": final_score,
        "personal_score": personal_score,
        "budget_score": budget_score,
        "budget_amount": budget_amount,
        "budget_label": budget_label,
        "serious_score": serious_score,
        "negative_score": negative_score,
        "matched_priority_keywords": [kw for kw, _ in matched_priority],
        "matched_negative_keywords": [kw for kw, _ in matched_negative],
        "matched_seriousness_indicators": [kw for kw, _ in matched_serious],
        "excluded_from_email": excluded_from_email,
        "recommendation": recommendation,
        "reasons": reasons,
    }


def apply_v11_scoring(enriched_project: dict) -> dict:
    """Mutate one enriched project with v1.1 scoring fields and return it."""
    details = score_project(enriched_project["project"], float(enriched_project.get("composite", 0)))
    enriched_project["base_composite"] = enriched_project.get("composite", 0)
    enriched_project["composite"] = details["final_score"]
    enriched_project["personal_scoring"] = details
    enriched_project["project"]["final_score"] = details["final_score"]
    enriched_project["project"]["budget_label"] = details["budget_label"]
    enriched_project["project"]["score_reason"] = " | ".join(details["reasons"])
    return enriched_project


def _normalized_words(text: str) -> set[str]:
    text = _to_western_digits(text.lower())
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[^\w\u0600-\u06FF]+", " ", text)
    return {word for word in text.split() if len(word) >= 3}


def _similarity(a: dict, b: dict) -> float:
    a_project = a["project"]
    b_project = b["project"]
    a_title = str(a_project.get("title", "")).strip().lower()
    b_title = str(b_project.get("title", "")).strip().lower()
    if a_title and b_title and (a_title in b_title or b_title in a_title):
        return 0.9

    a_words = _normalized_words(a_title + " " + str(a_project.get("description", "")))
    b_words = _normalized_words(b_title + " " + str(b_project.get("description", "")))
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / len(a_words | b_words)


def _source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source.title() if source else "Unknown")


def smart_dedupe_for_email(enriched_projects: list[dict], threshold: float = 0.58) -> list[dict]:
    """
    Report-only fuzzy dedupe. It keeps seen_ids.json behavior intact and only
    collapses near-duplicates before email rendering.
    """
    groups: list[dict] = []
    for ep in enriched_projects:
        placed = False
        for group in groups:
            if _similarity(ep, group["winner"]) >= threshold:
                group["items"].append(ep)
                placed = True
                break
        if not placed:
            groups.append({"winner": ep, "items": [ep]})

    winners: list[dict] = []
    for group in groups:
        items = group["items"]
        winner = max(
            items,
            key=lambda item: (
                float(item.get("composite", 0)),
                bool(item["project"].get("url")),
            ),
        )
        sources = []
        source_urls = {}
        for item in items:
            source = item["project"].get("source", "")
            label = _source_label(source)
            if label not in sources:
                sources.append(label)
            if item["project"].get("url"):
                source_urls[label] = item["project"]["url"]
        winner["appeared_sources"] = sources
        winner["source_urls"] = source_urls
        winners.append(winner)

    winners.sort(key=lambda item: (not item.get("is_golden"), -float(item.get("composite", 0))))
    return winners


def category_counts(projects: list[dict]) -> dict:
    counts = Counter()
    for ep in projects:
        project = ep.get("project", ep)
        text = _project_text(project).lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(keyword.lower() in text for keyword in keywords):
                counts[category] += 1
    return dict(counts)


def build_email_stats(
    *,
    total_collected: int,
    new_count: int,
    sent_count: int,
    all_projects: list[dict],
    email_projects: list[dict],
) -> dict:
    by_source = Counter(project.get("source", "bahr") for project in all_projects)
    return {
        "total_collected": total_collected,
        "new_opportunities": new_count,
        "sent_opportunities": sent_count,
        "by_source": {
            _source_label(source): count
            for source, count in by_source.items()
        },
        "top_categories": category_counts(email_projects),
    }


def build_weekly_summary(project_history: list[dict], current_email_projects: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    weekly: list[dict] = []
    for project in project_history:
        try:
            discovered = datetime.fromisoformat(str(project.get("discovered_at", "")))
            if discovered.tzinfo is None:
                discovered = discovered.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if discovered >= week_ago:
            weekly.append(project)

    for ep in current_email_projects:
        p = dict(ep["project"])
        p["composite_score"] = ep.get("composite", 0)
        weekly.append(p)

    by_source = Counter(_source_label(p.get("source", "bahr")) for p in weekly)
    top_keywords = Counter()
    for project in weekly:
        text = _project_text(project).lower()
        for keyword, _ in PERSONAL_KEYWORDS:
            if keyword.lower() in text:
                top_keywords[keyword] += 1

    best = sorted(
        weekly,
        key=lambda p: float(p.get("composite_score") or p.get("final_score") or 0),
        reverse=True,
    )[:5]

    return {
        "total_opportunities_this_week": len(weekly),
        "by_source": dict(by_source),
        "top_keywords": dict(top_keywords.most_common(8)),
        "best_5": best,
    }
