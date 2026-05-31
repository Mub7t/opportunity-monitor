"""
email_template.py — Gmail-compatible v1.1 Arabic RTL email report.
"""

from __future__ import annotations

from datetime import datetime
from html import escape


def _safe(value) -> str:
    return escape(str(value or ""), quote=True)


def _source_label(source: str) -> str:
    return {
        "bahr": "Bahr",
        "mostaql": "Mostaql",
        "telegram": "Telegram",
    }.get(source, source.title() if source else "Unknown")


def _score_color(score: float) -> str:
    if score >= 85:
        return "#0f766e"
    if score >= 70:
        return "#2563eb"
    if score >= 50:
        return "#b45309"
    return "#b91c1c"


def _summary_card(label: str, value: str, color: str) -> str:
    return f"""
    <td width="25%" style="padding:6px">
      <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:22px;font-weight:800;color:{color};line-height:1.2">{_safe(value)}</div>
        <div style="font-size:12px;color:#6b7280;margin-top:4px">{_safe(label)}</div>
      </div>
    </td>
    """


def _stats_section(stats: dict | None) -> str:
    if not stats:
        return ""
    by_source = stats.get("by_source", {})
    source_text = " / ".join(f"{_safe(k)}: {_safe(v)}" for k, v in by_source.items()) or "—"
    top_categories = stats.get("top_categories", {})
    category_text = " / ".join(f"{_safe(k)}: {_safe(v)}" for k, v in top_categories.items()) or "—"

    return f"""
    <tr>
      <td style="padding:18px 22px;background:#f8fafc;border-bottom:1px solid #e5e7eb">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            {_summary_card("تم جمعها", stats.get("total_collected", 0), "#334155")}
            {_summary_card("جديدة", stats.get("new_opportunities", 0), "#2563eb")}
            {_summary_card("في التقرير", stats.get("sent_opportunities", 0), "#0f766e")}
            {_summary_card("المصادر", len(by_source), "#7c3aed")}
          </tr>
        </table>
        <div style="font-size:12px;color:#475569;margin-top:10px;line-height:1.8">
          <b>حسب المصدر:</b> {source_text}<br>
          <b>أبرز الفئات:</b> {category_text}
        </div>
      </td>
    </tr>
    """


def _weekly_summary_section(summary: dict | None) -> str:
    if not summary:
        return ""
    by_source = " / ".join(
        f"{_safe(k)}: {_safe(v)}" for k, v in summary.get("by_source", {}).items()
    ) or "—"
    top_keywords = " / ".join(
        f"{_safe(k)}: {_safe(v)}" for k, v in summary.get("top_keywords", {}).items()
    ) or "—"
    best_items = "".join(
        f"<li><a href='{_safe(item.get('url', '#'))}' style='color:#2563eb;text-decoration:none'>{_safe(item.get('title', '')[:80])}</a></li>"
        for item in summary.get("best_5", [])
    )

    return f"""
    <tr>
      <td style="padding:0 22px 18px;background:#f8fafc">
        <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:14px">
          <div style="font-size:15px;font-weight:800;color:#9a3412;margin-bottom:8px">ملخص الأسبوع</div>
          <div style="font-size:13px;color:#7c2d12;line-height:1.9">
            <b>إجمالي فرص الأسبوع:</b> {_safe(summary.get("total_opportunities_this_week", 0))}<br>
            <b>حسب المصدر:</b> {by_source}<br>
            <b>أعلى الكلمات:</b> {top_keywords}
            {f"<ul style='margin:8px 0 0;padding-right:18px'>{best_items}</ul>" if best_items else ""}
          </div>
        </div>
      </td>
    </tr>
    """


def _market_section(report: dict | None) -> str:
    if not report:
        return ""
    period = report.get("period_summary", {})
    rising = report.get("rising_categories", [])[:3]
    signals = report.get("new_opportunity_signals", [])[:3]
    rising_html = "".join(f"<li>{_safe(r.get('category'))}: +{_safe(r.get('growth_pct'))}%</li>" for r in rising)
    signals_html = "".join(f"<li>{_safe(signal)}</li>" for signal in signals)

    return f"""
    <tr>
      <td style="padding:0 22px 18px;background:#f8fafc">
        <div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:8px;padding:14px">
          <div style="font-size:15px;font-weight:800;color:#3730a3;margin-bottom:8px">ذكاء السوق</div>
          <div style="font-size:13px;color:#312e81;line-height:1.9">
            <b>مشاريع هذا الأسبوع:</b> {_safe(period.get("this_week_projects", 0))}<br>
            <b>متوسط فرصة الفوز:</b> {_safe(round(period.get("avg_win_probability", 0) or 0))}%
            {f"<br><b>فئات في ارتفاع:</b><ul style='margin:6px 0;padding-right:18px'>{rising_html}</ul>" if rising_html else ""}
            {f"<b>إشارات:</b><ul style='margin:6px 0;padding-right:18px'>{signals_html}</ul>" if signals_html else ""}
          </div>
        </div>
      </td>
    </tr>
    """


def _opportunity_card(ep: dict, index: int) -> str:
    project = ep.get("project", {})
    analysis = ep.get("analysis", {})
    scoring = ep.get("personal_scoring", {})
    score = float(ep.get("composite", scoring.get("final_score", analysis.get("score", 0))) or 0)
    color = _score_color(score)
    source = _source_label(project.get("source", ""))
    appeared = ep.get("appeared_sources") or [source]
    appeared_text = " / ".join(_safe(item) for item in appeared)
    budget = scoring.get("budget_label") or project.get("budget") or "غير مذكورة"
    url = project.get("url") or "#"
    description = project.get("description") or analysis.get("summary") or project.get("raw_text", "")
    description = " ".join(str(description).split())[:360]
    reasons = scoring.get("reasons") or [analysis.get("score_reason", "")]
    reasons_html = "".join(f"<li>{_safe(reason)}</li>" for reason in reasons if reason)
    recommendation = scoring.get("recommendation") or "⚠️ متوسط"

    return f"""
    <tr>
      <td style="padding:0 22px 18px;background:#f8fafc">
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-right:5px solid {color};border-radius:8px;overflow:hidden">
          <div style="padding:16px 18px 10px">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="vertical-align:top">
                  <div style="font-size:12px;color:#64748b;margin-bottom:7px">
                    #{index} · <span style="background:#e0f2fe;color:#075985;border-radius:999px;padding:3px 9px">{_safe(source)}</span>
                    <span style="background:#f1f5f9;color:#475569;border-radius:999px;padding:3px 9px;margin-right:5px">ظهر في: {appeared_text}</span>
                  </div>
                  <div style="font-size:18px;font-weight:800;color:#111827;line-height:1.45">{_safe(project.get("title", "بدون عنوان"))}</div>
                </td>
                <td width="96" style="text-align:left;vertical-align:top">
                  <div style="display:inline-block;background:{color};color:#ffffff;border-radius:999px;padding:7px 12px;font-weight:800;font-size:14px">{score:.0f}/100</div>
                </td>
              </tr>
            </table>
            <div style="margin-top:10px;font-size:13px;color:#475569;line-height:1.8">{_safe(description)}</div>
            <div style="margin-top:12px;font-size:13px;color:#334155;line-height:1.8">
              <b>التوصية:</b> {_safe(recommendation)}<br>
              <b>الميزانية:</b> {_safe(budget)}<br>
              <b>التصنيف:</b> {_safe(analysis.get("category", project.get("category", "غير محدد")))}
            </div>
            {f"<ul style='margin:10px 0 0;padding-right:19px;font-size:12px;color:#475569;line-height:1.7'>{reasons_html}</ul>" if reasons_html else ""}
          </div>
          <div style="padding:12px 18px 16px;background:#f9fafb;border-top:1px solid #eef2f7">
            <a href="{_safe(url)}"
               style="display:inline-block;background:{color};color:#ffffff;text-decoration:none;border-radius:6px;padding:9px 18px;font-size:13px;font-weight:800">
              فتح رابط التقديم
            </a>
          </div>
        </div>
      </td>
    </tr>
    """


def build_v11_html_email(
    enriched_projects: list[dict],
    market_report: dict | None = None,
    run_stats: dict | None = None,
    weekly_summary: dict | None = None,
) -> str:
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    top_projects = enriched_projects[:10]
    cards = "".join(_opportunity_card(ep, i + 1) for i, ep in enumerate(top_projects))

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#e5e7eb;font-family:Arial,Tahoma,'Segoe UI',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr>
<td align="center" style="padding:26px 12px">
  <table width="680" cellpadding="0" cellspacing="0" style="max-width:680px;background:#f8fafc;border-radius:10px;overflow:hidden;border:1px solid #d1d5db">
    <tr>
      <td style="background:#111827;padding:26px 24px;color:#ffffff">
        <div style="font-size:24px;font-weight:900;line-height:1.4">Opportunity Monitor v1.1</div>
        <div style="font-size:13px;color:#cbd5e1;margin-top:6px">أفضل 10 فرص مناسبة لمهاراتك · {today}</div>
      </td>
    </tr>
    {_stats_section(run_stats)}
    {_weekly_summary_section(weekly_summary)}
    {_market_section(market_report)}
    <tr>
      <td style="padding:18px 22px 10px;background:#f8fafc">
        <div style="font-size:17px;font-weight:900;color:#111827">أفضل الفرص الآن</div>
        <div style="font-size:12px;color:#64748b;margin-top:4px">تم ترتيبها حسب التقييم الشخصي، الميزانية، جدية العميل، وتقييم الذكاء الاصطناعي.</div>
      </td>
    </tr>
    {cards}
    <tr>
      <td style="padding:18px 22px;text-align:center;font-size:12px;color:#94a3b8;background:#ffffff;border-top:1px solid #e5e7eb">
        تم الإرسال تلقائيًا من Opportunity Monitor v1.1
      </td>
    </tr>
  </table>
</td>
</tr>
</table>
</body>
</html>"""
