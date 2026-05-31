"""
notifier_email.py — Professional HTML email digest with color-coded project cards. (v3)

v3 additions:
  - Golden opportunity badge + special card styling
  - Win probability (real engine) displayed prominently
  - Similarity / trend notes in cards
  - Profile match indicator
  - Market intelligence summary section when available
  - Retry logic for SMTP send
"""

import smtplib
import logging
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import EMAIL_ENABLED, EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER, KEYWORDS
from email_template import build_v11_html_email

log = logging.getLogger(__name__)


# ─── Color helpers ────────────────────────────────────────────────────────────

def _card_colors(score: int, is_golden: bool) -> tuple[str, str]:
    """Return (border_color, badge_bg)."""
    if is_golden:
        return "#b8860b", "#fffde7"   # gold
    if score >= 70:
        return "#28a745", "#d4edda"   # green
    if score >= 40:
        return "#ffc107", "#fff3cd"   # yellow
    return "#dc3545", "#f8d7da"       # red


def _rec_label(rec: str) -> str:
    return {"Apply": "✅ قدّم الآن", "Consider": "⚠️ راجع", "Skip": "❌ تجاهل"}.get(rec, rec)


def _highlight_keywords(text: str) -> str:
    for kw in KEYWORDS:
        text = text.replace(
            kw,
            f"<mark style='background:#fff3cd;padding:0 2px;border-radius:2px'>{kw}</mark>"
        )
    return text


# ─── Card HTML ────────────────────────────────────────────────────────────────

def _project_card_html(ep: dict, index: int) -> str:
    p          = ep["project"]
    analysis   = ep["analysis"]
    proposal   = ep.get("proposal", "")
    win_result = ep.get("win_prob_result", {})
    sim_result = ep.get("similarity_result", {})
    is_golden  = ep.get("is_golden", False)
    prof_match = ep.get("profile_match", {})

    score   = analysis.get("score", 50)
    rec     = analysis.get("recommendation", "Consider")
    summary = analysis.get("summary", "")
    cat     = analysis.get("category", "")
    profit  = analysis.get("profitability", "—")
    urgency = analysis.get("urgency", "—")
    reason  = analysis.get("score_reason", "")
    skills  = ", ".join(analysis.get("skills", []))

    border, badge_bg = _card_colors(score, is_golden)
    title    = _highlight_keywords(p.get("title", "(بدون عنوان)"))
    url      = p.get("url", "#")
    desc     = p.get("description", "")[:200]
    proposal_short = proposal[:420] + ("…" if len(proposal) > 420 else "")

    # Win probability block
    win_prob    = win_result.get("probability", 0)
    win_conf    = win_result.get("confidence", "")
    win_explain = win_result.get("explanation", "")
    win_html = f"""
    <tr>
      <td style="padding:6px 18px">
        <div style="background:#e8f5e9;border-radius:8px;padding:10px 14px;
                    border-right:3px solid #28a745">
          <b>🎯 احتمال الفوز: {win_prob}%</b>
          <span style="color:#666;font-size:12px"> (ثقة: {win_conf})</span>
          <div style="font-size:11px;color:#555;margin-top:4px;direction:rtl;
                      white-space:pre-line">{win_explain}</div>
        </div>
      </td>
    </tr>
    """ if win_result else ""

    # Similarity block
    sim_projects = sim_result.get("similar_projects", [])
    trend_note   = sim_result.get("trend_note", "")
    sim_html = ""
    if sim_projects or trend_note:
        sim_items = "".join(
            f"<li><a href='{s['url']}' style='color:#0d6efd'>{s['title'][:55]}</a>"
            f" ({int(s['similarity']*100)}%)</li>"
            for s in sim_projects[:3]
        )
        sim_html = f"""
        <tr>
          <td style="padding:4px 18px">
            <div style="background:#f3e5f5;border-radius:6px;padding:8px 12px;
                        font-size:12px;color:#555;border-right:3px solid #9c27b0">
              🔗 مشاريع مشابهة سابقة: <ul style="margin:4px 0;padding-right:16px">{sim_items}</ul>
              {"<i>" + trend_note + "</i>" if trend_note else ""}
            </div>
          </td>
        </tr>
        """ if sim_items else ""

    # Profile match indicator
    prof_score    = prof_match.get("score", 0)
    prof_explain  = prof_match.get("explanation", "")
    prof_bar_w    = max(4, prof_score)
    prof_html = f"""
    <tr>
      <td style="padding:4px 18px;font-size:12px;color:#555">
        👤 تطابق الملف الشخصي: <b>{prof_score}%</b>
        <div style="background:#eee;border-radius:4px;height:6px;margin:3px 0;overflow:hidden">
          <div style="background:{border};width:{prof_bar_w}%;height:6px"></div>
        </div>
        <span style="font-size:11px;color:#777">{prof_explain}</span>
      </td>
    </tr>
    """ if prof_match else ""

    # Golden badge
    golden_header = ""
    if is_golden:
        golden_header = """
        <tr>
          <td style="background:linear-gradient(135deg,#f9a825,#f57f17);
                     padding:8px 16px;text-align:center">
            <span style="color:#fff;font-size:14px;font-weight:700">
              🥇 ⭐ فرصة ذهبية — تقديم فوري موصى به ⭐ 🥇
            </span>
          </td>
        </tr>
        """

    return f"""
<table width="100%" cellpadding="0" cellspacing="0"
       style="margin-bottom:22px;border-radius:10px;overflow:hidden;
              border:2px solid {border};background:#fff;
              box-shadow:0 2px 10px rgba(0,0,0,.08)">

  {golden_header}

  <!-- Header strip -->
  <tr>
    <td style="background:{border};padding:8px 16px">
      <span style="color:#fff;font-size:13px;font-weight:600">
        #{index} · {cat}
      </span>
      <span style="float:left;background:rgba(255,255,255,.25);
                   color:#fff;padding:2px 10px;border-radius:12px;font-size:12px">
        {_rec_label(rec)}
      </span>
    </td>
  </tr>

  <!-- Title + score -->
  <tr>
    <td style="padding:14px 18px 8px">
      <div style="font-size:16px;font-weight:700;color:#1a1a2e;margin-bottom:6px">
        {title}
      </div>
      <div style="font-size:13px;color:#555;margin-bottom:10px">{desc}</div>
      <table cellpadding="0" cellspacing="0">
        <tr>
          <td style="background:{badge_bg};border:1px solid {border};
                     border-radius:20px;padding:4px 14px">
            <span style="font-size:14px;font-weight:700;color:{border}">{score}/100</span>
          </td>
          <td width="12"></td>
          <td style="font-size:12px;color:#666">
            💰 ربحية: <b>{profit}</b> &nbsp;|&nbsp; ⏱ عجلة: <b>{urgency}</b>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  {win_html}

  {"" if not summary else f'''
  <tr>
    <td style="padding:6px 18px">
      <div style="background:#f0f4ff;border-radius:8px;padding:10px 14px;
                  font-size:13px;color:#333;border-right:3px solid #0d6efd">
        <b>📝 ملخص AI:</b> {summary}
      </div>
    </td>
  </tr>
  '''}

  {prof_html}
  {sim_html}

  {"" if not skills else f'<tr><td style="padding:4px 18px;font-size:12px;color:#555">🛠 المهارات المطلوبة: {skills}</td></tr>'}
  {"" if not reason else f'<tr><td style="padding:4px 18px;font-size:12px;color:#888;font-style:italic">💡 {reason}</td></tr>'}

  <!-- Proposal -->
  <tr>
    <td style="padding:10px 18px">
      <details style="border:1px solid #dee2e6;border-radius:6px;padding:8px 12px">
        <summary style="cursor:pointer;font-size:13px;font-weight:600;color:#0d6efd">
          ✍️ مسودة العرض (انقر للعرض)
        </summary>
        <pre style="white-space:pre-wrap;font-family:inherit;font-size:13px;
                    color:#333;margin:10px 0 0;direction:rtl">{proposal_short}</pre>
      </details>
    </td>
  </tr>

  <tr>
    <td style="padding:12px 18px 16px">
      <a href="{url}"
         style="display:inline-block;background:{border};color:#fff;
                text-decoration:none;padding:8px 20px;border-radius:6px;
                font-size:13px;font-weight:600">
        عرض المشروع ←
      </a>
    </td>
  </tr>

</table>
"""


# ─── Market intelligence section ─────────────────────────────────────────────

def _market_section_html(report: dict | None) -> str:
    if not report:
        return ""
    period = report.get("period_summary", {})
    rising = report.get("rising_categories", [])[:3]
    signals = report.get("new_opportunity_signals", [])

    if not rising and not signals:
        return ""

    rising_html = "".join(
        f"<li>{r['category']}: +{r['growth_pct']}% هذا الأسبوع</li>"
        for r in rising
    )
    signals_html = "".join(f"<li>{s}</li>" for s in signals)

    return f"""
<table width="100%" cellpadding="0" cellspacing="0"
       style="margin-bottom:24px;border-radius:10px;overflow:hidden;
              border:1px solid #b8860b;background:#fffde7">
  <tr>
    <td style="background:#f9a825;padding:10px 18px">
      <span style="color:#fff;font-size:14px;font-weight:700">
        📊 ذكاء السوق الأسبوعي — {report.get('week_label', '')}
      </span>
    </td>
  </tr>
  <tr>
    <td style="padding:14px 18px;font-size:13px;color:#333">
      <b>مشاريع هذا الأسبوع:</b> {period.get('this_week_projects', 0)} &nbsp;|&nbsp;
      <b>متوسط فرصة الفوز:</b> {period.get('avg_win_probability', 0):.0f}%
      {'<br><b>📈 فئات في ارتفاع:</b><ul style="margin:6px 0;padding-right:18px">' + rising_html + '</ul>' if rising_html else ''}
      {'<br><b>💡 إشارات:</b><ul style="margin:6px 0;padding-right:18px">' + signals_html + '</ul>' if signals_html else ''}
    </td>
  </tr>
</table>
"""


# ─── Full email builder ───────────────────────────────────────────────────────

def build_html_email(
    enriched_projects: list[dict],
    market_report: dict | None = None,
    run_stats: dict | None = None,
    weekly_summary: dict | None = None,
) -> str:
    if any("personal_scoring" in ep for ep in enriched_projects) or run_stats or weekly_summary:
        return build_v11_html_email(
            enriched_projects[:10],
            market_report=market_report,
            run_stats=run_stats,
            weekly_summary=weekly_summary,
        )

    today   = datetime.now().strftime("%Y-%m-%d %H:%M")
    total   = len(enriched_projects)
    golden  = sum(1 for ep in enriched_projects if ep.get("is_golden"))
    top     = sum(1 for ep in enriched_projects if ep["analysis"].get("score", 0) >= 70)

    cards = "".join(
        _project_card_html(ep, i + 1) for i, ep in enumerate(enriched_projects)
    )
    kw_badges = "&nbsp;".join(
        f"<span style='background:#e7f1ff;color:#0d6efd;padding:2px 8px;"
        f"border-radius:20px;font-size:11px'>{kw}</span>"
        for kw in KEYWORDS
    )

    market_html = _market_section_html(market_report)

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f0f2f5;
             font-family:'Segoe UI',Tahoma,Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:30px 15px">

  <table width="680" cellpadding="0" cellspacing="0"
         style="background:#fff;border-radius:14px;overflow:hidden;
                box-shadow:0 4px 20px rgba(0,0,0,.10)">

    <!-- Header -->
    <tr>
      <td style="background:linear-gradient(135deg,#0d6efd,#6610f2);
                 padding:32px 28px;text-align:center">
        <div style="font-size:30px;margin-bottom:6px">🌊</div>
        <h1 style="margin:0;color:#fff;font-size:24px;font-weight:700">
          تقرير مشاريع بحر
        </h1>
        <p style="margin:8px 0 0;color:rgba(255,255,255,.85);font-size:13px">{today}</p>
      </td>
    </tr>

    <!-- Stats -->
    <tr>
      <td style="padding:20px 28px;background:#f8f9fa;border-bottom:1px solid #dee2e6">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td align="center" style="padding:10px;background:#fff;border-radius:8px;
                border:1px solid #dee2e6">
              <div style="font-size:26px;font-weight:700;color:#0d6efd">{total}</div>
              <div style="font-size:12px;color:#6c757d">مشروع مطابق</div>
            </td>
            <td width="10"></td>
            <td align="center" style="padding:10px;background:#fff;border-radius:8px;
                border:1px solid #dee2e6">
              <div style="font-size:26px;font-weight:700;color:#b8860b">{golden}</div>
              <div style="font-size:12px;color:#6c757d">فرصة ذهبية</div>
            </td>
            <td width="10"></td>
            <td align="center" style="padding:10px;background:#fff;border-radius:8px;
                border:1px solid #dee2e6">
              <div style="font-size:26px;font-weight:700;color:#28a745">{top}</div>
              <div style="font-size:12px;color:#6c757d">ممتاز (70+)</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- Keywords -->
    <tr>
      <td style="padding:12px 28px;background:#f0f4ff;
                 border-bottom:1px solid #dee2e6;font-size:12px;color:#555">
        🔍 كلمات البحث:&nbsp;{kw_badges}
      </td>
    </tr>
    <tr>
      <td style="padding:8px 28px;font-size:11px;color:#888;
                 border-bottom:1px solid #f0f0f0">
        🥇 ذهبي &nbsp;|&nbsp; 🟢 ممتاز (≥70) &nbsp;|&nbsp;
        🟡 متوسط (40-69) &nbsp;|&nbsp; 🔴 منخفض (&lt;40)
      </td>
    </tr>

    <!-- Market intelligence (optional) -->
    {"" if not market_html else f'<tr><td style="padding:20px 28px 0">{market_html}</td></tr>'}

    <!-- Cards -->
    <tr>
      <td style="padding:24px 28px">{cards}</td>
    </tr>

    <!-- Footer -->
    <tr>
      <td style="padding:18px 28px;border-top:1px solid #dee2e6;
                 text-align:center;font-size:12px;color:#adb5bd">
        تم الإرسال تلقائيًا · بحر مراقب المشاريع v3 ·
        <a href="https://bahr.sa/projects" style="color:#0d6efd">عرض جميع المشاريع</a>
      </td>
    </tr>

  </table>
</td></tr>
</table>
</body>
</html>"""


# ─── Send function ────────────────────────────────────────────────────────────

def send_email(
    enriched_projects: list[dict],
    market_report: dict | None = None,
    run_stats: dict | None = None,
    weekly_summary: dict | None = None,
) -> None:
    """Send the HTML email digest. market_report is optional."""
    if not EMAIL_ENABLED:
        log.info("Email disabled — skipping.")
        return
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        log.warning("Email credentials missing — skipping.")
        return

    enriched_projects = enriched_projects[:10]
    count   = len(enriched_projects)
    golden  = sum(1 for ep in enriched_projects if ep.get("is_golden"))
    subject = (
        f"[Opportunity Monitor v1.1] أفضل {count} فرص"
        + (f" — {golden} ذهبي ⭐" if golden else "")
        + f" — {datetime.now().strftime('%Y-%m-%d')}"
    )
    html_body = build_html_email(
        enriched_projects,
        market_report=market_report,
        run_stats=run_stats,
        weekly_summary=weekly_summary,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    for attempt in range(1, 4):
        try:
            log.info("Sending email digest (%d projects) — attempt %d …", count, attempt)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
            log.info("Email sent successfully.")
            return
        except Exception as exc:
            log.warning("Email send attempt %d failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)
    log.error("All email send attempts failed.")
