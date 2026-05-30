"""
config.py — Centralized configuration for Bahr Monitor v3.
All tuneable parameters live here. Override via environment variables or .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"true", "1", "yes"}


# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR          = Path(__file__).parent
SEEN_IDS_FILE     = BASE_DIR / "seen_ids.json"
DB_FILE           = BASE_DIR / "projects.db"          # NEW: SQLite project history
PREFERENCES_FILE  = BASE_DIR / "preferences.json"     # NEW: personal learning data
MARKET_REPORT_FILE = BASE_DIR / "market_report.json"  # NEW: weekly market data

# ─── Email ────────────────────────────────────────────────────────────────────
EMAIL_ENABLED   = os.environ.get("EMAIL_ENABLED", "true").lower() == "true"
EMAIL_SENDER    = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD  = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER  = os.environ.get("EMAIL_RECEIVER", "")

# ─── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_ENABLED    = _env_bool("TELEGRAM_ENABLED", False)
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_SCRAPER_ENABLED = _env_bool("TELEGRAM_SCRAPER_ENABLED", False)
TELEGRAM_MIN_SCORE       = _env_int("TELEGRAM_MIN_SCORE", 80)

# ─── AI Analysis ──────────────────────────────────────────────────────────────
AI_ENABLED        = os.environ.get("AI_ENABLED", "false").lower() == "true"
AI_PROVIDER       = os.environ.get("AI_PROVIDER", "openai")   # openai | anthropic
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
AI_MODEL          = os.environ.get("AI_MODEL", "gpt-4o-mini")

# ─── Notification thresholds (NEW: tiered system) ─────────────────────────────
MIN_NOTIFY_SCORE     = _env_int("MIN_NOTIFY_SCORE", 60)    # normal
HIGH_PRIORITY_SCORE  = _env_int("HIGH_PRIORITY_SCORE", 75) # high priority
GOLDEN_SCORE         = _env_int("GOLDEN_SCORE", 90)        # golden opportunity

# Golden Opportunity: must meet ALL of these thresholds
GOLDEN_MIN_SCORE         = _env_int("GOLDEN_MIN_SCORE", 85)
GOLDEN_MIN_WIN_PCT       = _env_int("GOLDEN_MIN_WIN_PCT", 50)
GOLDEN_PROFITABILITY     = os.environ.get("GOLDEN_PROFITABILITY", "high")  # high|medium

# ─── Scraping ─────────────────────────────────────────────────────────────────
PROJECTS_URL      = "https://bahr.sa/projects"
PAGE_LOAD_TIMEOUT = 30_000   # ms
SCROLL_PAUSE_MS   = 1_500    # ms
MAX_SCROLL_STEPS  = _env_int("MAX_SCROLL_STEPS", 8)

# ─── Retry / reliability ──────────────────────────────────────────────────────
SCRAPE_MAX_RETRIES   = _env_int("SCRAPE_MAX_RETRIES", 3)
SCRAPE_RETRY_DELAY_S = _env_int("SCRAPE_RETRY_DELAY_S", 15)
AI_MAX_RETRIES       = _env_int("AI_MAX_RETRIES", 2)
RATE_LIMIT_DELAY_S   = _env_float("RATE_LIMIT_DELAY_S", 1.0)

# ─── Keywords ─────────────────────────────────────────────────────────────────
KEYWORDS = [
    "تصوير", "مونتاج", "موشن", "تصميم", "فيديو", "موقع", "برمجة",
    "ذكاء اصطناعي", "أتمتة", "إعلان", "هوية بصرية", "محتوى",
    "سوشال ميديا", "جرافيك", "شات بوت", "متجر إلكتروني", "تطبيق",
    "بايثون", "API", "تحليل بيانات", "automation", "AI",
]

# ─── User profile — Mubarak's skill matrix ────────────────────────────────────
USER_PROFILE = {
    "name":        os.environ.get("PROFILE_NAME", "مبارك"),
    "title":       os.environ.get("PROFILE_TITLE", "مطور ويب ومصور محترف"),
    "skills":      os.environ.get(
        "PROFILE_SKILLS",
        "تصوير، فيديو، موشن جرافيك، تصميم جرافيك، تطوير ويب، ذكاء اصطناعي، أتمتة، استشارات تقنية"
    ),
    "experience":  os.environ.get("PROFILE_EXPERIENCE", "5+ سنوات"),
    "portfolio":   os.environ.get("PROFILE_PORTFOLIO", ""),
    "contact":     os.environ.get("PROFILE_CONTACT", ""),
}

# NEW: Skill domains with profile match weights (higher = stronger match for Mubarak)
# Weight 1.0 = core skill, 0.5 = secondary, 0.2 = peripheral
SKILL_DOMAINS = {
    # Video & Photo — core
    "تصوير":          1.0,
    "فيديو":          1.0,
    "مونتاج":         1.0,
    "موشن جرافيك":    1.0,
    "موشن":           1.0,
    "انتاج فيديو":    1.0,
    "إنتاج فيديو":    1.0,
    "تصوير فوتوغرافي":1.0,
    # Design — core
    "تصميم":          0.9,
    "جرافيك":         0.9,
    "هوية بصرية":     0.9,
    "تصميم جرافيك":   0.9,
    "هوية":           0.85,
    "إعلان":          0.8,
    "سوشال ميديا":    0.8,
    "محتوى":          0.75,
    # Web dev — core
    "موقع":           0.9,
    "تطوير ويب":      0.9,
    "برمجة":          0.85,
    "تطبيق":          0.8,
    "متجر إلكتروني":  0.8,
    # AI & automation — core
    "ذكاء اصطناعي":   1.0,
    "أتمتة":          1.0,
    "automation":     1.0,
    "AI":             1.0,
    "شات بوت":        0.9,
    # Technical
    "بايثون":         0.85,
    "API":            0.8,
    "تحليل بيانات":   0.75,
    "استشارات":       0.7,
}

# ─── Scoring weights ──────────────────────────────────────────────────────────
SCORE_WEIGHTS = {
    "ai_score":          0.30,   # AI suitability score
    "keyword_relevance": 0.20,   # keyword matches
    "profitability":     0.15,   # AI profitability estimate
    "urgency":           0.10,   # AI urgency level
    "profile_match":     0.15,   # NEW: Mubarak's skill domain match
    "preference_boost":  0.10,   # NEW: personal learning system boost
}

# Win probability engine weights (NEW)
WIN_PROB_WEIGHTS = {
    "proposal_count":  0.30,   # fewer proposals = better odds
    "project_age":     0.20,   # newer = better odds
    "profile_match":   0.25,   # skill match
    "budget_range":    0.15,   # budget attractiveness
    "ai_estimate":     0.10,   # AI component (minor)
}

# ─── Dashboard ────────────────────────────────────────────────────────────────
DASHBOARD_ENABLED = os.environ.get("DASHBOARD_ENABLED", "false").lower() == "true"
DASHBOARD_HOST    = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT    = _env_int("DASHBOARD_PORT", 5001)

# ─── Market intelligence ──────────────────────────────────────────────────────
MARKET_REPORT_DAY = _env_int("MARKET_REPORT_DAY", 0)  # 0=Mon, 6=Sun
SIMILARITY_THRESHOLD = _env_float("SIMILARITY_THRESHOLD", 0.55)
