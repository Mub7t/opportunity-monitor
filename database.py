"""
database.py — SQLite long-term project history and personal preferences store.

Tables:
  projects        — every project ever discovered, with full analysis
  preferences     — user applied/ignored signals for preference learning
  market_snapshots— weekly category/budget aggregates for market intelligence
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import DB_FILE

log = logging.getLogger(__name__)

# ─── Schema ───────────────────────────────────────────────────────────────────

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id              TEXT    PRIMARY KEY,
    source          TEXT    NOT NULL DEFAULT 'bahr',
    title           TEXT    NOT NULL DEFAULT '',
    url             TEXT    NOT NULL DEFAULT '',
    description     TEXT    DEFAULT '',
    category        TEXT    DEFAULT '',
    discovered_at   TEXT    NOT NULL,
    ai_score        INTEGER DEFAULT 0,
    composite_score REAL    DEFAULT 0,
    win_probability REAL    DEFAULT 0,
    win_confidence  TEXT    DEFAULT 'low',
    win_explanation TEXT    DEFAULT '',
    profitability   TEXT    DEFAULT '',
    urgency         TEXT    DEFAULT '',
    recommendation  TEXT    DEFAULT '',
    is_golden       INTEGER DEFAULT 0,
    proposal        TEXT    DEFAULT '',
    full_analysis   TEXT    DEFAULT '{}',
    status          TEXT    DEFAULT 'new',
    similarity_ids  TEXT    DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_projects_discovered ON projects(discovered_at);
CREATE INDEX IF NOT EXISTS idx_projects_category   ON projects(category);
CREATE INDEX IF NOT EXISTS idx_projects_golden     ON projects(is_golden);

CREATE TABLE IF NOT EXISTS preferences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT    NOT NULL,
    action          TEXT    NOT NULL,   -- applied | ignored | viewed | starred
    category        TEXT    DEFAULT '',
    budget_range    TEXT    DEFAULT '',
    recorded_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pref_action     ON preferences(action);
CREATE INDEX IF NOT EXISTS idx_pref_category   ON preferences(category);
CREATE INDEX IF NOT EXISTS idx_pref_project    ON preferences(project_id);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT    NOT NULL,
    category        TEXT    NOT NULL,
    project_count   INTEGER DEFAULT 0,
    avg_ai_score    REAL    DEFAULT 0,
    avg_win_prob    REAL    DEFAULT 0,
    golden_count    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_market_date     ON market_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_market_category ON market_snapshots(category);
"""

# ─── Connection management ────────────────────────────────────────────────────

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript(_DDL)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "source" not in cols:
            conn.execute("ALTER TABLE projects ADD COLUMN source TEXT NOT NULL DEFAULT 'bahr'")
        conn.execute("UPDATE projects SET source='bahr' WHERE source IS NULL OR source=''")
    log.info("Database initialized at %s", DB_FILE)


# ─── Projects ─────────────────────────────────────────────────────────────────

def upsert_project(
    project: dict,
    analysis: dict,
    proposal: str,
    composite_score: float,
    win_prob_result: dict,
    is_golden: bool,
    similarity_ids: list[str],
) -> None:
    """Insert or update a project record."""
    pid = project.get("id", project.get("url", ""))
    now = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO projects
                (id, source, title, url, description, category, discovered_at,
                 ai_score, composite_score, win_probability, win_confidence,
                 win_explanation, profitability, urgency, recommendation,
                 is_golden, proposal, full_analysis, status, similarity_ids)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                source           = excluded.source,
                title            = excluded.title,
                url              = excluded.url,
                description      = excluded.description,
                composite_score  = excluded.composite_score,
                win_probability  = excluded.win_probability,
                win_confidence   = excluded.win_confidence,
                win_explanation  = excluded.win_explanation,
                is_golden        = excluded.is_golden,
                full_analysis    = excluded.full_analysis,
                similarity_ids   = excluded.similarity_ids
        """, (
            pid,
            project.get("source", "bahr"),
            project.get("title", ""),
            project.get("url", ""),
            project.get("description", ""),
            analysis.get("category", ""),
            now,
            analysis.get("score", 0),
            composite_score,
            win_prob_result.get("probability", 0),
            win_prob_result.get("confidence", "low"),
            win_prob_result.get("explanation", ""),
            analysis.get("profitability", ""),
            analysis.get("urgency", ""),
            analysis.get("recommendation", ""),
            1 if is_golden else 0,
            proposal,
            json.dumps(analysis, ensure_ascii=False),
            "new",
            json.dumps(similarity_ids, ensure_ascii=False),
        ))


def _with_dashboard_source_label(project: dict) -> dict:
    """Keep DB title clean, but expose source clearly to the existing dashboard."""
    source = project.get("source") or "bahr"
    label = "Mostaql" if source == "mostaql" else "Bahr"
    title = project.get("title", "")
    project["source"] = source
    project["raw_title"] = title
    if title and not title.startswith(("Bahr: ", "Mostaql: ")):
        project["title"] = f"{label}: {title}"
    return project


def get_all_projects(limit: int = 500) -> list[dict]:
    """Fetch recent projects for dashboard and similarity checks."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY discovered_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_with_dashboard_source_label(dict(r)) for r in rows]


def get_project_by_id(pid: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    return _with_dashboard_source_label(dict(row)) if row else None


def get_stats() -> dict:
    """Return aggregate statistics for the dashboard."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        golden = conn.execute("SELECT COUNT(*) FROM projects WHERE is_golden=1").fetchone()[0]
        today_str = datetime.now(timezone.utc).date().isoformat()
        today_count = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE discovered_at LIKE ?", (f"{today_str}%",)
        ).fetchone()[0]
        avg_score = conn.execute("SELECT AVG(composite_score) FROM projects").fetchone()[0] or 0
        avg_win = conn.execute("SELECT AVG(win_probability) FROM projects").fetchone()[0] or 0

        # Projects this week
        from datetime import timedelta
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        week_count = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE discovered_at >= ?", (week_ago,)
        ).fetchone()[0]

        # Top categories (last 7 days)
        cat_rows = conn.execute("""
            SELECT category, COUNT(*) as cnt
            FROM projects
            WHERE discovered_at >= ? AND category != ''
            GROUP BY category ORDER BY cnt DESC LIMIT 10
        """, (week_ago,)).fetchall()

    return {
        "total_projects":  total,
        "golden_total":    golden,
        "today_count":     today_count,
        "week_count":      week_count,
        "avg_score":       round(avg_score, 1),
        "avg_win_prob":    round(avg_win, 1),
        "top_categories":  [{"category": r["category"], "count": r["cnt"]} for r in cat_rows],
    }


# ─── Preferences ──────────────────────────────────────────────────────────────

def record_preference(project_id: str, action: str, category: str = "", budget_range: str = "") -> None:
    """Record a user interaction signal. action: applied|ignored|viewed|starred"""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO preferences (project_id, action, category, budget_range, recorded_at)
            VALUES (?,?,?,?,?)
        """, (project_id, action, category, budget_range, now))
    log.debug("Preference recorded: %s → %s", project_id[:30], action)


def get_preference_stats() -> dict:
    """Aggregate preference statistics for the learning system."""
    with get_conn() as conn:
        # Applied categories
        applied_cats = conn.execute("""
            SELECT category, COUNT(*) as cnt
            FROM preferences
            WHERE action='applied' AND category != ''
            GROUP BY category ORDER BY cnt DESC
        """).fetchall()

        # Ignored categories
        ignored_cats = conn.execute("""
            SELECT category, COUNT(*) as cnt
            FROM preferences
            WHERE action='ignored' AND category != ''
            GROUP BY category ORDER BY cnt DESC
        """).fetchall()

        # Total signals
        total_applied  = conn.execute("SELECT COUNT(*) FROM preferences WHERE action='applied'").fetchone()[0]
        total_ignored  = conn.execute("SELECT COUNT(*) FROM preferences WHERE action='ignored'").fetchone()[0]
        total_starred  = conn.execute("SELECT COUNT(*) FROM preferences WHERE action='starred'").fetchone()[0]

    return {
        "applied_categories": {r["category"]: r["cnt"] for r in applied_cats},
        "ignored_categories": {r["category"]: r["cnt"] for r in ignored_cats},
        "total_applied":  total_applied,
        "total_ignored":  total_ignored,
        "total_starred":  total_starred,
    }


# ─── Market snapshots ─────────────────────────────────────────────────────────

def save_market_snapshot(snapshot_date: str, category_stats: list[dict]) -> None:
    """Persist weekly market intelligence data."""
    with get_conn() as conn:
        # Delete existing entries for this date to allow re-runs
        conn.execute("DELETE FROM market_snapshots WHERE snapshot_date=?", (snapshot_date,))
        for row in category_stats:
            conn.execute("""
                INSERT INTO market_snapshots
                    (snapshot_date, category, project_count, avg_ai_score, avg_win_prob, golden_count)
                VALUES (?,?,?,?,?,?)
            """, (
                snapshot_date,
                row.get("category", ""),
                row.get("project_count", 0),
                row.get("avg_ai_score", 0),
                row.get("avg_win_prob", 0),
                row.get("golden_count", 0),
            ))


def get_market_history(weeks: int = 8) -> list[dict]:
    """Fetch historical market snapshots for trend analysis."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM market_snapshots
            ORDER BY snapshot_date DESC, project_count DESC
            LIMIT ?
        """, (weeks * 50,)).fetchall()
    return [dict(r) for r in rows]
