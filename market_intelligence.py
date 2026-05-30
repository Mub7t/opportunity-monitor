"""
market_intelligence.py — Market Intelligence Module

Generates weekly reports showing:
  - Most common categories
  - Rising vs declining categories (week-over-week)
  - Average budgets by category
  - Competition trends (avg proposal counts)
  - Golden opportunity trends
  - New opportunity signals

Runs automatically on the configured weekday (default: Monday).
Output: market_report.json + Telegram/email summary.
"""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from config import MARKET_REPORT_FILE, MARKET_REPORT_DAY

log = logging.getLogger(__name__)


def _week_label(dt: datetime) -> str:
    """Return ISO week label like '2025-W22'."""
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def is_market_report_day() -> bool:
    """Return True if today is the configured market report weekday."""
    return datetime.now(timezone.utc).weekday() == MARKET_REPORT_DAY


def build_market_report(projects: list[dict]) -> dict:
    """
    Build a comprehensive market intelligence report from the project history.

    Args:
        projects: list of project dicts from database.get_all_projects()

    Returns:
        report dict with categories, trends, budgets, etc.
    """
    if not projects:
        return {"error": "No project data available", "generated_at": datetime.now(timezone.utc).isoformat()}

    now = datetime.now(timezone.utc)
    week_ago    = now - timedelta(days=7)
    two_weeks   = now - timedelta(days=14)

    # Partition by time window
    this_week   = []
    last_week   = []
    all_time    = projects

    for p in projects:
        try:
            dt = datetime.fromisoformat(p.get("discovered_at", ""))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= week_ago:
                this_week.append(p)
            elif dt >= two_weeks:
                last_week.append(p)
        except Exception:
            pass

    # ── Category analysis ─────────────────────────────────────────────────────
    def cat_counts(project_list: list) -> Counter:
        return Counter(
            p.get("category", "غير محدد") or "غير محدد"
            for p in project_list
        )

    this_week_cats = cat_counts(this_week)
    last_week_cats = cat_counts(last_week)
    all_time_cats  = cat_counts(all_time)

    # Rising: appeared more this week than last
    rising_cats = []
    for cat, count in this_week_cats.most_common(20):
        prev = last_week_cats.get(cat, 0)
        if count > 0 and (prev == 0 or count / max(prev, 1) >= 1.5):
            rising_cats.append({
                "category": cat,
                "this_week": count,
                "last_week": prev,
                "growth_pct": round((count - prev) / max(prev, 1) * 100) if prev > 0 else 100,
            })

    # Declining
    declining_cats = []
    for cat, prev in last_week_cats.most_common(15):
        curr = this_week_cats.get(cat, 0)
        if prev >= 3 and curr < prev * 0.5:
            declining_cats.append({
                "category": cat,
                "this_week": curr,
                "last_week": prev,
                "drop_pct": round((prev - curr) / prev * 100),
            })

    # ── Score & win stats ─────────────────────────────────────────────────────
    def avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    scores_by_cat = defaultdict(list)
    wins_by_cat   = defaultdict(list)
    golden_by_cat = Counter()

    for p in all_time:
        cat = p.get("category", "غير محدد") or "غير محدد"
        if p.get("composite_score"):
            scores_by_cat[cat].append(float(p["composite_score"]))
        if p.get("win_probability"):
            wins_by_cat[cat].append(float(p["win_probability"]))
        if p.get("is_golden"):
            golden_by_cat[cat] += 1

    category_stats = []
    for cat, total in all_time_cats.most_common(15):
        category_stats.append({
            "category":      cat,
            "total_count":   total,
            "this_week":     this_week_cats.get(cat, 0),
            "avg_score":     avg(scores_by_cat.get(cat, [])),
            "avg_win_prob":  avg(wins_by_cat.get(cat, [])),
            "golden_count":  golden_by_cat.get(cat, 0),
        })

    # ── Overall metrics ───────────────────────────────────────────────────────
    all_scores   = [float(p["composite_score"]) for p in all_time if p.get("composite_score")]
    all_wins     = [float(p["win_probability"])  for p in all_time if p.get("win_probability")]
    golden_total = sum(1 for p in all_time if p.get("is_golden"))

    # Competition pressure proxy: avg win_probability across all projects
    # Lower win_prob overall = more competition
    competition_pressure = "high" if avg(all_wins) < 35 else ("medium" if avg(all_wins) < 55 else "low")

    # ── New opportunity signals ───────────────────────────────────────────────
    new_signals = []
    for entry in rising_cats[:3]:
        cat = entry["category"]
        if entry["this_week"] >= 3:
            new_signals.append(
                f"📈 '{cat}' ارتفع {entry['growth_pct']}% هذا الأسبوع — فرصة متزايدة"
            )
    if competition_pressure == "low":
        new_signals.append("✨ المنافسة منخفضة بشكل عام هذا الأسبوع — وقت جيد للتقديم")

    report = {
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "week_label":         _week_label(now),
        "period_summary": {
            "this_week_projects":  len(this_week),
            "last_week_projects":  len(last_week),
            "total_all_time":      len(all_time),
            "golden_all_time":     golden_total,
            "avg_composite_score": avg(all_scores),
            "avg_win_probability": avg(all_wins),
            "competition_pressure": competition_pressure,
        },
        "top_categories":     category_stats[:10],
        "rising_categories":  rising_cats[:5],
        "declining_categories": declining_cats[:5],
        "new_opportunity_signals": new_signals,
        "this_week_golden":   [
            {"title": p.get("title", "")[:60], "category": p.get("category", ""), "url": p.get("url", "")}
            for p in this_week if p.get("is_golden")
        ][:10],
    }

    return report


def save_market_report(report: dict) -> None:
    """Save report to disk."""
    tmp = MARKET_REPORT_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    tmp.replace(MARKET_REPORT_FILE)
    log.info("Market report saved → %s", MARKET_REPORT_FILE)


def load_market_report() -> dict | None:
    """Load last saved market report."""
    if MARKET_REPORT_FILE.exists():
        try:
            with open(MARKET_REPORT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            log.error("Could not load market report: %s", exc)
    return None


def format_market_report_telegram(report: dict) -> str:
    """Format the weekly market report as a Telegram HTML message."""
    period = report.get("period_summary", {})
    top    = report.get("top_categories", [])[:5]
    rising = report.get("rising_categories", [])[:3]
    signals = report.get("new_opportunity_signals", [])
    week   = report.get("week_label", "")

    lines = [
        f"📊 <b>تقرير بحر الأسبوعي — {week}</b>\n",
        f"📦 مشاريع هذا الأسبوع: <b>{period.get('this_week_projects', 0)}</b>",
        f"⭐ فرص ذهبية: <b>{period.get('golden_all_time', 0)}</b>",
        f"🏆 متوسط فرصة الفوز: <b>{period.get('avg_win_probability', 0):.0f}%</b>",
        f"🔥 ضغط المنافسة: <b>{period.get('competition_pressure', '—')}</b>",
        "",
        "🏷 <b>أعلى الفئات هذا الأسبوع:</b>",
    ]
    for cat in top:
        lines.append(f"  • {cat['category']}: {cat['this_week']} مشروع (avg فوز: {cat['avg_win_prob']:.0f}%)")

    if rising:
        lines.append("\n📈 <b>الفئات في ارتفاع:</b>")
        for r in rising:
            lines.append(f"  • {r['category']} +{r['growth_pct']}%")

    if signals:
        lines.append("\n💡 <b>إشارات جديدة:</b>")
        lines.extend(signals)

    return "\n".join(lines)
