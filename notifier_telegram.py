"""
notifier_telegram.py — Tiered Telegram notification system (v3)

Notification tiers:
  🥇 GOLDEN     (score >= GOLDEN_SCORE)      — immediate, special formatting
  🔴 HIGH       (score >= HIGH_PRIORITY_SCORE) — high priority alert
  🟡 NORMAL     (score >= MIN_NOTIFY_SCORE)   — standard alert
  Weekly market report — special broadcast

All original behavior preserved.
"""

import json
import logging
import time
import urllib.request
import urllib.parse

from config import (
    TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    MIN_NOTIFY_SCORE, HIGH_PRIORITY_SCORE, GOLDEN_SCORE,
)

log = logging.getLogger(__name__)


# ─── Core send function ───────────────────────────────────────────────────────

def _send_message(text: str, retries: int = 2) -> bool:
    """Send a Telegram message with retry logic. Returns True on success."""
    if not TELEGRAM_ENABLED or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text[:4096],    # Telegram message limit
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return True
        except Exception as exc:
            log.warning("Telegram send attempt %d failed: %s", attempt + 1, exc)
            if attempt < retries:
                time.sleep(2 ** attempt)
    log.error("Telegram: all send attempts failed.")
    return False


# ─── Tier detection ───────────────────────────────────────────────────────────

def _tier(score: int, is_golden: bool) -> str:
    if is_golden:
        return "golden"
    if score >= HIGH_PRIORITY_SCORE:
        return "high"
    if score >= MIN_NOTIFY_SCORE:
        return "normal"
    return "skip"


def _tier_header(tier: str) -> str:
    return {
        "golden": "🥇 <b>فرصة ذهبية على بحر!</b>",
        "high":   "🔴 <b>مشروع ذو أولوية عالية</b>",
        "normal": "🟡 <b>مشروع جديد على بحر</b>",
    }.get(tier, "")


def _score_emoji(score: int) -> str:
    if score >= 80: return "🟢"
    if score >= 60: return "🟡"
    return "🔴"


def _rec_emoji(rec: str) -> str:
    return {"Apply": "✅", "Consider": "⚠️", "Skip": "❌"}.get(rec, "❓")


# ─── Project notification ─────────────────────────────────────────────────────

def notify_project(
    project: dict,
    analysis: dict,
    proposal: str,
    win_prob_result: dict | None = None,
    is_golden: bool = False,
    similarity_result: dict | None = None,
) -> None:
    """
    Send a tiered Telegram notification.
    All original parameters preserved; new ones are optional.
    """
    if not TELEGRAM_ENABLED:
        return

    score = analysis.get("score", 0)
    rec   = analysis.get("recommendation", "Consider")
    tier  = _tier(score, is_golden)

    if tier == "skip":
        log.info("Telegram skipped (score %d < threshold): %s", score, project.get("title", "")[:40])
        return

    title   = project.get("title", "(بدون عنوان)")
    url     = project.get("url", "#")
    summary = analysis.get("summary", "")
    cat     = analysis.get("category", "")
    profit  = analysis.get("profitability", "")
    urgency = analysis.get("urgency", "")

    # Win probability block (new)
    win_line = ""
    if win_prob_result:
        prob = win_prob_result.get("probability", 0)
        conf = win_prob_result.get("confidence", "")
        win_line = f"🎯 احتمال الفوز: <b>{prob}%</b> (ثقة: {conf})\n"
    else:
        win_line = f"🏆 فرصة الفوز (AI): {analysis.get('win_chance', '—')}\n"

    # Similarity block (new)
    sim_line = ""
    if similarity_result and similarity_result.get("similar_projects"):
        sim_count = len(similarity_result["similar_projects"])
        sim_line  = f"🔗 مشابه لـ {sim_count} مشروع سابق\n"

    # Short proposal
    short_proposal = proposal[:280].strip() + ("…" if len(proposal) > 280 else "")

    # Golden badge
    golden_badge = "🥇 <b>⭐ فرصة ذهبية ⭐</b>\n\n" if tier == "golden" else ""

    text = (
        f"{golden_badge}"
        f"{_tier_header(tier)}\n\n"
        f"📌 <b>{title}</b>\n"
        f"🔗 <a href='{url}'>عرض المشروع</a>\n\n"
        f"{_score_emoji(score)} النقاط: <b>{score}/100</b>  {_rec_emoji(rec)} {rec}\n"
        f"🏷 الفئة: {cat}\n"
        f"💰 الربحية: {profit}  |  ⏱ عجلة: {urgency}\n"
        f"{win_line}"
        f"{sim_line}"
        f"\n📝 <b>ملخص:</b>\n{summary}\n\n"
        f"✍️ <b>مسودة العرض:</b>\n<i>{short_proposal}</i>"
    )

    if _send_message(text):
        log.info("Telegram [%s] sent: %s (score=%d)", tier.upper(), title[:40], score)
    else:
        log.warning("Telegram notification failed for: %s", title[:40])


# ─── Golden opportunity dedicated alert ───────────────────────────────────────

def send_golden_alert(project: dict, analysis: dict, win_prob: dict, proposal: str) -> None:
    """Dedicated golden opportunity alert — bypasses score threshold checks."""
    if not TELEGRAM_ENABLED:
        return

    title   = project.get("title", "(بدون عنوان)")
    url     = project.get("url", "#")
    score   = analysis.get("score", 0)
    cat     = analysis.get("category", "")
    prob    = win_prob.get("probability", 0)
    conf    = win_prob.get("confidence", "")
    summary = analysis.get("summary", "")
    short_p = proposal[:250].strip() + ("…" if len(proposal) > 250 else "")

    text = (
        f"🥇🥇🥇 <b>فرصة ذهبية نادرة!</b> 🥇🥇🥇\n\n"
        f"⭐⭐⭐ <b>{title}</b> ⭐⭐⭐\n"
        f"🔗 <a href='{url}'>عرض المشروع الآن</a>\n\n"
        f"📊 النقاط: <b>{score}/100</b>\n"
        f"🎯 احتمال الفوز: <b>{prob}%</b> (ثقة: {conf})\n"
        f"🏷 الفئة: {cat}\n\n"
        f"📝 {summary}\n\n"
        f"✍️ مسودة العرض:\n<i>{short_p}</i>\n\n"
        f"⚡ <b>تقديم فوري موصى به!</b>"
    )

    if _send_message(text):
        log.info("GOLDEN ALERT sent: %s", title[:50])


# ─── Market report notification ───────────────────────────────────────────────

def send_market_report(report_text: str) -> None:
    """Broadcast the weekly market intelligence report."""
    if not TELEGRAM_ENABLED:
        return
    if _send_message(report_text):
        log.info("Weekly market report sent via Telegram.")
    else:
        log.warning("Market report Telegram send failed.")
