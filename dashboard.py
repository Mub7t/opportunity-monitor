"""
dashboard.py — Lightweight Flask Dashboard for Bahr Monitor (v3)

Provides a read-only web interface to browse discovered projects,
statistics, market trends, and manage basic preferences.

Start:  python dashboard.py
Or:     DASHBOARD_ENABLED=true python monitor.py  (auto-start in background)

Routes:
  GET  /                   — main dashboard
  GET  /projects           — project list with search/filter/sort
  GET  /project/<id>       — project detail
  GET  /stats              — stats JSON
  GET  /market             — market intelligence report
  POST /preference/<id>    — record applied|ignored|starred signal
  GET  /api/projects       — JSON API for projects
"""

import json
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask, render_template_string, request, jsonify, redirect, url_for

from config import DASHBOARD_HOST, DASHBOARD_PORT
from database import get_all_projects, get_stats, get_project_by_id, record_preference
from market_intelligence import load_market_report
from preference_engine import load_preferences, record_applied, record_ignored, record_starred

log = logging.getLogger(__name__)
app = Flask(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ago(iso_str: str) -> str:
    """Convert ISO timestamp to human-readable relative time."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        if delta.total_seconds() < 3600:
            return f"منذ {int(delta.total_seconds() // 60)} دقيقة"
        if delta.days == 0:
            return f"منذ {int(delta.total_seconds() // 3600)} ساعة"
        return f"منذ {delta.days} يوم"
    except Exception:
        return iso_str[:10]


def _score_class(score):
    if score is None: return "secondary"
    score = float(score)
    if score >= 85: return "warning"   # gold
    if score >= 70: return "success"
    if score >= 40: return "primary"
    return "danger"


# ─── Base template ────────────────────────────────────────────────────────────

_BASE_CSS = """
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<style>
  body { background:#f4f6fb; font-family:'Segoe UI',Tahoma,sans-serif; direction:rtl; }
  .navbar { background:linear-gradient(135deg,#0d6efd,#6610f2)!important; }
  .card { border:none; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,.08); }
  .golden-card { border:2px solid #f9a825!important; background:#fffde7!important; }
  .badge-golden { background:#f9a825; color:#333; }
  .stat-card { text-align:center; padding:20px 10px; }
  .stat-val { font-size:2.2rem; font-weight:700; }
  .win-bar { height:8px; border-radius:4px; background:#e9ecef; overflow:hidden; }
  .win-fill { height:100%; background:linear-gradient(90deg,#dc3545,#ffc107,#28a745); }
  .category-tag { display:inline-block; background:#e7f1ff; color:#0d6efd;
                  padding:2px 10px; border-radius:20px; font-size:12px; margin:2px; }
  pre { white-space:pre-wrap; font-family:inherit; font-size:13px; }
</style>
"""

_NAV = """
<nav class="navbar navbar-dark mb-4">
  <div class="container-fluid">
    <span class="navbar-brand fw-bold">🌊 بحر مراقب المشاريع</span>
    <div class="d-flex gap-3">
      <a href="/" class="text-white text-decoration-none">الرئيسية</a>
      <a href="/projects" class="text-white text-decoration-none">المشاريع</a>
      <a href="/market" class="text-white text-decoration-none">السوق</a>
    </div>
  </div>
</nav>
"""


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    stats = get_stats()
    prefs = load_preferences()
    recent = get_all_projects(limit=10)
    golden_recent = [p for p in recent if p.get("is_golden")][:5]

    top_cats_html = "".join(
        f'<span class="category-tag">{c["category"]} ({c["count"]})</span>'
        for c in stats.get("top_categories", [])[:8]
    )

    recent_cards = ""
    for p in recent[:6]:
        sc = float(p.get("composite_score") or 0)
        wp = float(p.get("win_probability") or 0)
        golden_cls = "golden-card" if p.get("is_golden") else ""
        recent_cards += f"""
        <div class="col-md-4 mb-3">
          <div class="card p-3 {golden_cls}">
            {'<span class="badge badge-golden mb-1">🥇 ذهبي</span>' if p.get("is_golden") else ""}
            <div class="fw-semibold mb-1" style="font-size:14px">
              <a href="/project/{p['id'].replace('/','__')}" class="text-decoration-none text-dark">
                {p.get('title','')[:55]}
              </a>
            </div>
            <span class="category-tag">{p.get('category','') or '—'}</span>
            <div class="d-flex justify-content-between align-items-center mt-2">
              <span class="badge bg-{_score_class(sc)}">{sc:.0f}/100</span>
              <small class="text-muted">{_ago(p.get('discovered_at',''))}</small>
            </div>
            <div class="win-bar mt-2">
              <div class="win-fill" style="width:{min(wp,100):.0f}%"></div>
            </div>
            <small class="text-muted">احتمال الفوز: {wp:.0f}%</small>
          </div>
        </div>
        """

    template = f"""<!DOCTYPE html><html dir="rtl" lang="ar">
<head>{_BASE_CSS}<title>بحر Monitor</title></head>
<body>{_NAV}
<div class="container-fluid px-4">
  <!-- Stats row -->
  <div class="row g-3 mb-4">
    <div class="col-6 col-md-2">
      <div class="card stat-card">
        <div class="stat-val text-primary">{stats.get('total_projects',0)}</div>
        <div class="text-muted small">إجمالي المشاريع</div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card stat-card">
        <div class="stat-val text-warning">{stats.get('golden_total',0)}</div>
        <div class="text-muted small">فرص ذهبية</div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card stat-card">
        <div class="stat-val text-success">{stats.get('today_count',0)}</div>
        <div class="text-muted small">اليوم</div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card stat-card">
        <div class="stat-val text-info">{stats.get('week_count',0)}</div>
        <div class="text-muted small">هذا الأسبوع</div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card stat-card">
        <div class="stat-val" style="color:#0d6efd">{stats.get('avg_score',0):.0f}</div>
        <div class="text-muted small">متوسط النقاط</div>
      </div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card stat-card">
        <div class="stat-val text-success">{stats.get('avg_win_prob',0):.0f}%</div>
        <div class="text-muted small">متوسط فرصة الفوز</div>
      </div>
    </div>
  </div>

  <!-- Preferences summary -->
  <div class="row mb-3">
    <div class="col">
      <div class="card p-3">
        <h6 class="fw-bold mb-2">📚 نظام التعلم الشخصي</h6>
        <div class="d-flex gap-4 flex-wrap">
          <span>✅ قدّمت: <b>{len(prefs.get('applied_projects',[]))}</b></span>
          <span>❌ تجاهلت: <b>{len(prefs.get('ignored_projects',[]))}</b></span>
          <span>⭐ مميزة: <b>{len(prefs.get('starred_projects',[]))}</b></span>
        </div>
      </div>
    </div>
  </div>

  <!-- Top categories -->
  <div class="card p-3 mb-4">
    <h6 class="fw-bold mb-2">🏷 أعلى الفئات</h6>
    {top_cats_html}
  </div>

  <!-- Recent projects -->
  <h5 class="fw-bold mb-3">🕒 آخر المشاريع</h5>
  <div class="row">{recent_cards}</div>

  <div class="text-center mt-3">
    <a href="/projects" class="btn btn-primary">عرض جميع المشاريع</a>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""
    return template


@app.route("/projects")
def projects_list():
    search   = request.args.get("q", "").strip()
    sort_by  = request.args.get("sort", "composite_score")
    category = request.args.get("cat", "").strip()
    golden_only = request.args.get("golden", "") == "1"

    all_p = get_all_projects(limit=300)

    # Filter
    if golden_only:
        all_p = [p for p in all_p if p.get("is_golden")]
    if category:
        all_p = [p for p in all_p if p.get("category", "") == category]
    if search:
        sl = search.lower()
        all_p = [p for p in all_p if sl in p.get("title", "").lower()
                 or sl in p.get("category", "").lower()]

    # Sort
    sort_key = {"composite_score": lambda x: -(float(x.get("composite_score") or 0)),
                "win_probability":  lambda x: -(float(x.get("win_probability") or 0)),
                "ai_score":        lambda x: -(float(x.get("ai_score") or 0)),
                "date":            lambda x: x.get("discovered_at", ""),
               }.get(sort_by, lambda x: -(float(x.get("composite_score") or 0)))
    all_p.sort(key=sort_key)

    # Unique categories for filter dropdown
    cats = sorted({p.get("category", "") for p in get_all_projects(100) if p.get("category")})

    rows = ""
    for p in all_p[:150]:
        sc = float(p.get("composite_score") or 0)
        wp = float(p.get("win_probability") or 0)
        pid_enc = p["id"].replace("/", "__")
        golden_badge = '<span class="badge badge-golden ms-1">🥇</span>' if p.get("is_golden") else ""
        rows += f"""
        <tr>
          <td>
            <a href="/project/{pid_enc}" class="text-decoration-none fw-semibold">
              {p.get('title','')[:60]}
            </a>{golden_badge}
          </td>
          <td><span class="category-tag">{p.get('category','') or '—'}</span></td>
          <td><span class="badge bg-{_score_class(sc)}">{sc:.0f}</span></td>
          <td>
            <div class="win-bar" style="width:80px;display:inline-block">
              <div class="win-fill" style="width:{min(wp,100):.0f}%"></div>
            </div>
            <small class="ms-1">{wp:.0f}%</small>
          </td>
          <td><small class="text-muted">{_ago(p.get('discovered_at',''))}</small></td>
          <td>
            <a href="/project/{pid_enc}" class="btn btn-sm btn-outline-primary">عرض</a>
          </td>
        </tr>
        """

    cat_options = "".join(
        f'<option value="{c}" {"selected" if c==category else ""}>{c}</option>'
        for c in cats
    )

    template = f"""<!DOCTYPE html><html dir="rtl" lang="ar">
<head>{_BASE_CSS}<title>المشاريع</title></head>
<body>{_NAV}
<div class="container-fluid px-4">
  <div class="card p-3 mb-3">
    <form method="get" class="row g-2 align-items-end">
      <div class="col-md-4">
        <input name="q" value="{search}" class="form-control"
               placeholder="بحث في العنوان أو الفئة…">
      </div>
      <div class="col-md-2">
        <select name="cat" class="form-select">
          <option value="">كل الفئات</option>
          {cat_options}
        </select>
      </div>
      <div class="col-md-2">
        <select name="sort" class="form-select">
          <option value="composite_score" {"selected" if sort_by=="composite_score" else ""}>ترتيب: النقاط</option>
          <option value="win_probability"  {"selected" if sort_by=="win_probability"  else ""}>ترتيب: الفوز</option>
          <option value="ai_score"         {"selected" if sort_by=="ai_score"         else ""}>ترتيب: AI</option>
          <option value="date"             {"selected" if sort_by=="date"             else ""}>ترتيب: التاريخ</option>
        </select>
      </div>
      <div class="col-md-2">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="golden" value="1"
                 id="goldenChk" {"checked" if golden_only else ""}>
          <label class="form-check-label" for="goldenChk">ذهبية فقط 🥇</label>
        </div>
      </div>
      <div class="col-md-2">
        <button class="btn btn-primary w-100">بحث</button>
      </div>
    </form>
  </div>

  <div class="card">
    <div class="table-responsive">
      <table class="table table-hover mb-0">
        <thead class="table-light">
          <tr>
            <th>العنوان</th><th>الفئة</th><th>النقاط</th>
            <th>فرصة الفوز</th><th>الوقت</th><th></th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
  <small class="text-muted mt-2 d-block">يعرض {min(len(all_p),150)} من {len(all_p)} نتيجة</small>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""
    return template


@app.route("/project/<pid_enc>")
def project_detail(pid_enc):
    pid = pid_enc.replace("__", "/")
    p = get_project_by_id(pid)
    if not p:
        return "المشروع غير موجود", 404

    analysis = json.loads(p.get("full_analysis") or "{}")
    sc   = float(p.get("composite_score") or 0)
    wp   = float(p.get("win_probability") or 0)
    golden_cls = "golden-card" if p.get("is_golden") else ""

    sim_ids = json.loads(p.get("similarity_ids") or "[]")
    sim_html = ""
    if sim_ids:
        sim_html = "<ul class='list-unstyled mb-0'>"
        for sid in sim_ids[:5]:
            sp = get_project_by_id(sid)
            if sp:
                sp_enc = sid.replace("/", "__")
                sim_html += f'<li>🔗 <a href="/project/{sp_enc}">{sp.get("title","")[:55]}</a></li>'
        sim_html += "</ul>"

    template = f"""<!DOCTYPE html><html dir="rtl" lang="ar">
<head>{_BASE_CSS}<title>{p.get('title','')[:40]}</title></head>
<body>{_NAV}
<div class="container px-4">
  <a href="/projects" class="btn btn-sm btn-outline-secondary mb-3">← رجوع</a>

  <div class="card p-4 mb-3 {golden_cls}">
    {'<div class="badge badge-golden fs-6 mb-2">🥇 فرصة ذهبية</div>' if p.get("is_golden") else ""}
    <h4 class="fw-bold">{p.get('title','')}</h4>
    <div class="mb-2">
      <span class="category-tag">{p.get('category','') or '—'}</span>
      <a href="{p.get('url','#')}" target="_blank" class="btn btn-primary btn-sm ms-2">
        عرض المشروع على بحر ←
      </a>
    </div>

    <div class="row g-3 my-2">
      <div class="col-6 col-md-3">
        <div class="card p-3 text-center">
          <div class="stat-val text-primary" style="font-size:1.8rem">{sc:.0f}</div>
          <small class="text-muted">النقاط المركّبة</small>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="card p-3 text-center">
          <div class="stat-val text-success" style="font-size:1.8rem">{wp:.0f}%</div>
          <small class="text-muted">احتمال الفوز</small>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="card p-3 text-center">
          <div class="stat-val" style="font-size:1.8rem;color:#0d6efd">{analysis.get('score',0)}</div>
          <small class="text-muted">نقاط AI</small>
        </div>
      </div>
      <div class="col-6 col-md-3">
        <div class="card p-3 text-center">
          <div class="stat-val text-warning" style="font-size:1.8rem">{p.get('win_confidence','')}</div>
          <small class="text-muted">مستوى الثقة</small>
        </div>
      </div>
    </div>

    <!-- Win explanation -->
    <div class="card p-3 mb-3" style="background:#e8f5e9">
      <h6 class="fw-bold">🎯 تفاصيل احتمال الفوز</h6>
      <pre style="font-size:12px">{p.get('win_explanation','—')}</pre>
    </div>

    <!-- AI summary -->
    <div class="card p-3 mb-3" style="background:#f0f4ff">
      <h6 class="fw-bold">🤖 تحليل AI</h6>
      <p>{analysis.get('summary','—')}</p>
      <div class="d-flex gap-3 flex-wrap text-sm">
        <span>💰 ربحية: <b>{analysis.get('profitability','—')}</b></span>
        <span>⏱ عجلة: <b>{analysis.get('urgency','—')}</b></span>
        <span>📋 توصية: <b>{analysis.get('recommendation','—')}</b></span>
      </div>
      {'<p class="text-muted mt-2 mb-0"><i>' + analysis.get('score_reason','') + '</i></p>' if analysis.get('score_reason') else ""}
    </div>

    <!-- Proposal -->
    <div class="card p-3 mb-3">
      <h6 class="fw-bold">✍️ مسودة العرض</h6>
      <pre>{p.get('proposal','—')}</pre>
    </div>

    <!-- Similar projects -->
    {"" if not sim_html else f'<div class="card p-3 mb-3"><h6 class="fw-bold">🔗 مشاريع مشابهة</h6>{sim_html}</div>'}

    <!-- Preference actions -->
    <div class="card p-3">
      <h6 class="fw-bold">📊 تفضيلاتك</h6>
      <div class="d-flex gap-2 flex-wrap">
        <form method="post" action="/preference/{pid_enc}">
          <input type="hidden" name="action" value="applied">
          <button class="btn btn-success btn-sm">✅ قدّمت على هذا</button>
        </form>
        <form method="post" action="/preference/{pid_enc}">
          <input type="hidden" name="action" value="starred">
          <button class="btn btn-warning btn-sm">⭐ مميز</button>
        </form>
        <form method="post" action="/preference/{pid_enc}">
          <input type="hidden" name="action" value="ignored">
          <button class="btn btn-outline-danger btn-sm">❌ تجاهل</button>
        </form>
      </div>
      <small class="text-muted mt-2 d-block">
        اكتُشف: {_ago(p.get('discovered_at',''))}
      </small>
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""
    return template


@app.route("/preference/<pid_enc>", methods=["POST"])
def record_pref(pid_enc):
    pid    = pid_enc.replace("__", "/")
    action = request.form.get("action", "viewed")
    p = get_project_by_id(pid)
    cat = p.get("category", "") if p else ""

    if action == "applied":
        record_applied(pid, cat, float((p or {}).get("composite_score") or 0))
        record_preference(pid, "applied", cat)
    elif action == "ignored":
        record_ignored(pid, cat)
        record_preference(pid, "ignored", cat)
    elif action == "starred":
        record_starred(pid, cat)
        record_preference(pid, "starred", cat)

    return redirect(url_for("project_detail", pid_enc=pid_enc))


@app.route("/market")
def market():
    report = load_market_report()
    if not report:
        return """<!DOCTYPE html><html dir="rtl" lang="ar">
        <head>""" + _BASE_CSS + """<title>السوق</title></head>
        <body>""" + _NAV + """
        <div class="container"><div class="alert alert-info mt-4">
          لا يتوفر تقرير سوق بعد. سيُنشأ تلقائياً في أول يوم إثنين.
        </div></div></body></html>"""

    period  = report.get("period_summary", {})
    rising  = report.get("rising_categories", [])
    top_cats = report.get("top_categories", [])[:10]
    signals  = report.get("new_opportunity_signals", [])

    top_rows = "".join(
        f"""<tr>
          <td><span class="category-tag">{c['category']}</span></td>
          <td>{c['this_week']}</td>
          <td>{c['total_count']}</td>
          <td><span class="badge bg-{_score_class(c['avg_score'])}">{c['avg_score']:.0f}</span></td>
          <td>{c['avg_win_prob']:.0f}%</td>
          <td>{'⭐'*c['golden_count'] if c['golden_count'] else '—'}</td>
        </tr>"""
        for c in top_cats
    )
    rising_html = "".join(
        f'<li class="mb-1">📈 <b>{r["category"]}</b>: +{r["growth_pct"]}% '
        f'({r["last_week"]}→{r["this_week"]} هذا الأسبوع)</li>'
        for r in rising[:5]
    )
    signals_html = "".join(f'<li>{s}</li>' for s in signals)

    template = f"""<!DOCTYPE html><html dir="rtl" lang="ar">
<head>{_BASE_CSS}<title>ذكاء السوق</title></head>
<body>{_NAV}
<div class="container-fluid px-4">
  <h5 class="fw-bold mb-3">📊 ذكاء السوق — {report.get('week_label','')}</h5>

  <div class="row g-3 mb-4">
    <div class="col-6 col-md-3">
      <div class="card stat-card">
        <div class="stat-val text-primary">{period.get('this_week_projects',0)}</div>
        <small class="text-muted">مشاريع هذا الأسبوع</small>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card stat-card">
        <div class="stat-val text-success">{period.get('avg_win_probability',0):.0f}%</div>
        <small class="text-muted">متوسط فرصة الفوز</small>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card stat-card">
        <div class="stat-val text-warning">{period.get('golden_all_time',0)}</div>
        <small class="text-muted">ذهبيات إجمالي</small>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card stat-card">
        <div class="stat-val" style="font-size:1.3rem;color:#dc3545">
          {period.get('competition_pressure','—')}
        </div>
        <small class="text-muted">ضغط المنافسة</small>
      </div>
    </div>
  </div>

  <div class="row g-3">
    <div class="col-md-7">
      <div class="card p-3">
        <h6 class="fw-bold">🏆 أعلى الفئات</h6>
        <table class="table table-sm">
          <thead class="table-light">
            <tr><th>الفئة</th><th>هذا الأسبوع</th><th>الإجمالي</th>
                <th>متوسط النقاط</th><th>فرصة الفوز</th><th>ذهبية</th></tr>
          </thead>
          <tbody>{top_rows}</tbody>
        </table>
      </div>
    </div>
    <div class="col-md-5">
      {'<div class="card p-3 mb-3"><h6 class="fw-bold">📈 فئات في ارتفاع</h6><ul>' + rising_html + '</ul></div>' if rising_html else ''}
      {'<div class="card p-3"><h6 class="fw-bold">💡 إشارات السوق</h6><ul>' + signals_html + '</ul></div>' if signals_html else ''}
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""
    return template


@app.route("/stats")
def stats_json():
    return jsonify(get_stats())


@app.route("/api/projects")
def api_projects():
    limit = min(int(request.args.get("limit", 50)), 200)
    sort  = request.args.get("sort", "composite_score")
    projects = get_all_projects(limit=limit)
    return jsonify({"projects": projects, "count": len(projects)})


# ─── Standalone entry point ───────────────────────────────────────────────────

def run_dashboard():
    log.info("Starting dashboard on http://%s:%d", DASHBOARD_HOST, DASHBOARD_PORT)
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_dashboard()
