"""
monitor.py — Bahr.sa Smart Project Monitor (v3)
================================================
Full pipeline:
  scrape → deduplicate → keyword filter → AI analyze → win probability →
  profile match → preference boost → composite score → similarity check →
  golden detection → tiered notifications → email → DB persist → market report

NEVER re-notifies previously reported projects.
"""

import logging
import asyncio
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import (
    PROJECTS_URL, PAGE_LOAD_TIMEOUT, SCROLL_PAUSE_MS, MAX_SCROLL_STEPS,
    KEYWORDS, SCORE_WEIGHTS, SCRAPE_MAX_RETRIES, SCRAPE_RETRY_DELAY_S,
    GOLDEN_MIN_SCORE, GOLDEN_MIN_WIN_PCT, GOLDEN_PROFITABILITY,
    HIGH_PRIORITY_SCORE, SIMILARITY_THRESHOLD, TELEGRAM_SCRAPER_ENABLED,
    TELEGRAM_MIN_SCORE, EMAIL_ENABLED, EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER,
)
from storage import load_seen_db, save_seen_db, is_seen, mark_seen
from database import init_db, upsert_project, get_all_projects, get_stats
from ai_analyzer import analyze_project
from proposal_generator import generate_proposal
from win_probability import compute_win_probability
from profile_matcher import compute_profile_match, profile_relevance_score
from preference_engine import (
    compute_preference_boost, auto_learn_from_high_scores, get_preference_summary,
)
from similarity import find_similar_projects
from market_intelligence import (
    build_market_report, save_market_report, is_market_report_day,
    format_market_report_telegram,
)
from notifier_telegram import (
    notify_project, send_golden_alert, send_market_report as tg_market_report,
)
from notifier_email import send_email
from mostaql_scraper import scrape_mostaql_projects
from telegram_scraper import scrape_telegram_opportunities

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── Title / category extraction helpers ─────────────────────────────────────

# Labels that appear as badge text in bahr.sa cards — never a real project title.
# Kept as a frozenset for O(1) lookup.
_LABEL_WORDS: frozenset[str] = frozenset([
    # Payment type badges
    "بالمشروع", "شهري", "بالساعة", "بالكلمة", "بالصفحة", "بالتسليم",
    # Work location badges
    "عن بعد", "في المكتب", "هجين", "عن_بعد",
    # Status badges
    "مفتوح", "مغلق", "قيد التنفيذ", "مكتمل", "ملغي",
    # Noise fragments often seen as first lines
    "ريال", "عروض", "منذ", "جديد", "مميز", "featured", "new",
    "sr", "sar", "open", "closed", "remote", "onsite", "hybrid",
    # Single characters / punctuation that can appear as a line
    "·", "•", "-", "|", "/",
])

# Minimum character length for a string to be considered a real title.
_MIN_TITLE_LEN = 6


def _is_label(text: str) -> bool:
    """Return True if the text is a known badge/label, NOT a real title."""
    t = text.strip()
    if len(t) < 2:
        return True
    # Exact match against known labels (case-insensitive)
    if t.lower() in {lw.lower() for lw in _LABEL_WORDS}:
        return True
    # Short text made only of digits, spaces, or currency symbols — e.g. "500 ريال"
    import re
    if re.fullmatch(r"[\d\s,،.ريال$€£]+", t, re.UNICODE):
        return True
    # Looks like a time string: "منذ 3 ساعات", "3 days ago", "منذ دقيقتين"
    if re.search(r"منذ|ago|ساعة|دقيق|يوم|أسبوع|شهر|سنة", t):
        return True
    # Looks like a proposal count: "5 عروض", "0 عروض"
    if re.search(r"\d+\s*عروض?|\d+\s*proposal", t, re.IGNORECASE):
        return True
    return False


def _extract_title_from_lines(lines: list[str]) -> str:
    """
    Walk through card text lines and return the first line that:
      - is not a known label / badge
      - has at least _MIN_TITLE_LEN characters
      - contains at least one Arabic or Latin letter

    Falls back to the longest non-label line if nothing passes, then
    to '(بدون عنوان)' as last resort.
    """
    import re
    has_letter = re.compile(r"[a-zA-Z\u0600-\u06FF]")

    candidates = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_label(stripped):
            continue
        if len(stripped) < _MIN_TITLE_LEN:
            continue
        if not has_letter.search(stripped):
            continue
        candidates.append(stripped)

    if candidates:
        return candidates[0]   # first passing line is the title

    # Fallback: longest non-label line
    non_label = [l.strip() for l in lines if l.strip() and not _is_label(l.strip())]
    if non_label:
        return max(non_label, key=len)

    return "(بدون عنوان)"


# Category keywords → canonical Arabic category name.
# Checked against the full raw card text (not just title) for better coverage.
_CATEGORY_MAP: list[tuple[list[str], str]] = [
    (["تصوير فوتوغرافي", "تصوير احترافي", "فوتوغراف"],          "تصوير فوتوغرافي"),
    (["موشن جرافيك", "motion graphic", "موشن"],                  "موشن جرافيك"),
    (["مونتاج", "تحرير فيديو", "video edit"],                    "مونتاج فيديو"),
    (["إنتاج فيديو", "انتاج فيديو", "تصوير فيديو", "فيديو"],    "إنتاج فيديو"),
    (["تصوير"],                                                   "تصوير"),
    (["هوية بصرية", "هوية تجارية", "برanding", "brand"],         "هوية بصرية"),
    (["تصميم جرافيك", "جرافيك ديزاين", "graphic design"],        "تصميم جرافيك"),
    (["تصميم شعار", "لوجو", "logo"],                              "تصميم شعار"),
    (["ui", "ux", "واجهة مستخدم", "تجربة مستخدم"],               "UI/UX تصميم"),
    (["تصميم موقع", "web design"],                               "تصميم مواقع"),
    (["تصميم"],                                                   "تصميم"),
    (["سوشال ميديا", "social media", "منصات التواصل"],           "سوشال ميديا"),
    (["محتوى", "كتابة إبداعية", "copywriting"],                  "كتابة محتوى"),
    (["إعلان", "حملة إعلانية", "تسويق"],                         "تسويق وإعلان"),
    (["متجر إلكتروني", "shopify", "woocommerce"],                "متجر إلكتروني"),
    (["تطبيق موبايل", "mobile app", "ios", "android"],           "تطبيق موبايل"),
    (["موقع إلكتروني", "موقع ويب", "wordpress", "تطوير موقع"],   "تطوير مواقع"),
    (["برمجة", "تطوير"],                                          "برمجة"),
    (["شات بوت", "chatbot"],                                      "شات بوت"),
    (["أتمتة", "automation", "n8n", "zapier"],                    "أتمتة"),
    (["ذكاء اصطناعي", "ai", "machine learning", "chatgpt", "بوت", "bot"], "ذكاء اصطناعي"),
    (["بايثون", "python", "javascript", "react", "node"],        "برمجة"),
    (["api", "تكامل", "integration"],                            "تطوير API"),
    (["تحليل بيانات", "data analysis", "excel", "إكسل"],         "تحليل بيانات"),
    (["ترجمة"],                                                   "ترجمة"),
    (["استشارات", "consulting"],                                  "استشارات"),
]


def _detect_category(raw_text: str, title: str) -> str:
    """
    Scan the card's full text against CATEGORY_MAP keyword lists.
    Returns the matched category name, or empty string if no match.
    AI will still override this when enabled — this is a fast fallback.
    """
    haystack = (title + " " + raw_text).lower()
    for keywords, category in _CATEGORY_MAP:
        for kw in keywords:
            if kw.lower() in haystack:
                return category
    return ""


# ─── Scraping with retry ──────────────────────────────────────────────────────

def _do_scrape() -> list[dict]:
    """Single scrape attempt. Raises on failure."""
    projects = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            locale="ar-SA",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        log.info("Opening %s …", PROJECTS_URL)
        page.goto(PROJECTS_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

        CARD_SELECTORS = [
            "article",
            "[data-testid='project-card']",
            "a[href*='/projects/']",
            ".project-card",
        ]
        card_selector = None
        for sel in CARD_SELECTORS:
            try:
                page.wait_for_selector(sel, timeout=10_000)
                card_selector = sel
                log.info("Project cards found with selector: %s", sel)
                break
            except PWTimeout:
                continue

        if card_selector is None:
            browser.close()
            raise RuntimeError("No project card selector matched — page structure may have changed.")

        for step in range(MAX_SCROLL_STEPS):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(SCROLL_PAUSE_MS)

        # ── JavaScript: extract rich card data including semantic title selectors ──
        evaluate_js = r"""
            () => {
                // Known label/badge text that is NOT a project title.
                // Mirrors the Python _LABEL_WORDS set.
                const LABEL_SET = new Set([
                    'بالمشروع','شهري','بالساعة','بالكلمة','بالصفحة','بالتسليم',
                    'عن بعد','في المكتب','هجين','عن_بعد',
                    'مفتوح','مغلق','قيد التنفيذ','مكتمل','ملغي',
                    'ريال','عروض','منذ','جديد','مميز','featured','new',
                    'sr','sar','open','closed','remote','onsite','hybrid',
                    '·','•','-','|','/',
                ]);

                function isLabel(text) {
                    const t = text.trim().toLowerCase();
                    if (t.length < 2) return true;
                    if (LABEL_SET.has(t) || LABEL_SET.has(text.trim())) return true;
                    // Only letters test - no regex, use char code ranges
                    var hasLetter = false;
                    for (var ci = 0; ci < t.length; ci++) {
                        var cc = t.charCodeAt(ci);
                        // Arabic U+0600-U+06FF, Latin lowercase a-z
                        if ((cc >= 0x0600 && cc <= 0x06FF) || (cc >= 0x61 && cc <= 0x7A)) {
                            hasLetter = true; break;
                        }
                    }
                    if (!hasLetter) return true;
                    // Time strings - safe indexOf, no regex
                    if (t.indexOf('منذ') !== -1 || t.indexOf('ago') !== -1 ||
                        t.indexOf('ساعة') !== -1 || t.indexOf('دقيق') !== -1 ||
                        t.indexOf('يوم') !== -1 || t.indexOf('أسبوع') !== -1 ||
                        t.indexOf('شهر') !== -1 || t.indexOf('سنة') !== -1) return true;
                    // Proposal counts - safe indexOf, no regex
                    if (t.indexOf('عروض') !== -1 || t.indexOf('proposal') !== -1) return true;
                    return false;
                }

                function extractTitle(card) {
                    // Strategy 1: look for semantic heading or title element inside card
                    const titleSelectors = [
                        'h3[class*="line-clamp-3"]',
                        'h1','h2','h3','h4',
                        '[class*="title"]',
                        '[class*="Title"]',
                        '[class*="name"]',
                        '[class*="Name"]',
                        '[class*="heading"]',
                        '[class*="Heading"]',
                        '[class*="project-name"]',
                        '[class*="projectName"]',
                        '[class*="card-title"]',
                        'p:first-of-type',
                    ];
                    for (const sel of titleSelectors) {
                        try {
                            const el = card.querySelector(sel);
                            if (el) {
                                const t = el.innerText.trim();
                                if (t.length >= 6 && !isLabel(t)) return t;
                            }
                        } catch(e) {}
                    }

                    // Strategy 2: find ALL text nodes / leaf elements and filter labels
                    const allText = card.innerText || '';
                    const lines = allText.split('\n').map(l => l.trim()).filter(Boolean);
                    // hasLetter check uses charCode (no regex)
                    for (const line of lines) {
                        var _hl=false;
                        for(var _i=0;_i<line.length;_i++){
                            var _c=line.charCodeAt(_i);
                            if((_c>=0x0600&&_c<=0x06FF)||(_c>=0x41&&_c<=0x7A)){_hl=true;break;}
                        }
                        if (!isLabel(line) && line.length >= 6 && _hl) {
                            return line;
                        }
                    }
                    // Strategy 3: fallback — longest non-label line
                    const nonLabel = lines.filter(l => !isLabel(l) && l.length > 0);
                    if (nonLabel.length > 0) {
                        return nonLabel.reduce((a, b) => a.length >= b.length ? a : b);
                    }

                    return '(بدون عنوان)';
                }

                function extractDescription(card, titleText) {
                    const allText = card.innerText || '';
                    const lines = allText.split('\n').map(l => l.trim()).filter(Boolean);
                    // Return up to 3 lines that are not the title and not labels
                    const desc = [];
                    for (const line of lines) {
                        if (line === titleText) continue;
                        if (line.length < 4) continue;
                        // Skip pure-label lines and time/count lines
                        // Skip time strings and proposal counts - indexOf, no regex
                        if (line.indexOf('منذ') !== -1 || line.indexOf('ago') !== -1 ||
                            line.indexOf('عروض') !== -1 || line.indexOf('proposal') !== -1) continue;
                        // Skip digit/currency-only lines - charCode check, no regex
                        var dHL=false; for(var di=0;di<line.length;di++){var dc=line.charCodeAt(di);
                            if((dc>=0x0600&&dc<=0x06FF)||(dc>=0x61&&dc<=0x7A)){dHL=true;break;}}
                        if (!dHL) continue;
                        desc.push(line);
                        if (desc.length >= 3) break;
                    }
                    return desc.join(' ');
                }

                const results = [];
                const links = Array.from(
                    document.querySelectorAll("a[href*='/projects/']")
                );
                const seen = new Set();

                for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    if (href.trim() === '/projects' || href.trim() === '/projects/') continue;
                    // Skip only genuinely deep sub-paths like /projects/123/proposals/456.
                    // Allow depth ≤ 4 to cover locale-prefixed URLs: /ar/projects/123 (depth=3)
                    if ((href.split('/').length - 1) > 4) continue;
                    if (seen.has(href)) continue;
                    seen.add(href);

                    const card = a.querySelector('article') || a.closest('article') || a.closest('li')
                               || a.closest('[class*="card"]') || a.parentElement || a;

                    const allText = card.innerText || '';
                    const cardHtml = card.outerHTML || '';
                    const title   = extractTitle(card);
                    const desc    = extractDescription(card, title);

                    // Debug: log first 3 cards to console (visible in Playwright stderr)
                    if (results.length < 3) {
                        console.log('DEBUG card[' + results.length + ']: href=' + href
                            + ' | title=' + title
                            + ' | raw=' + allText.substring(0, 120).replace(/\n/g, '↵'));
                    }

                    results.push({
                        url:         'https://bahr.sa' + href,
                        id:          href,
                        title:       title,
                        description: desc,
                        raw_text:    allText,
                        card_html:   cardHtml.substring(0, 1000),
                    });
                }
                console.log('SUCCESS: extracted ' + results.length + ' project URLs');
                return results;
            }
            """
        log.info("page.evaluate JavaScript block:\n%s", evaluate_js)

        try:
            page.evaluate("(source) => { new Function('return (' + source + ')'); return true; }", evaluate_js)
            raw_projects = page.evaluate(evaluate_js)
        except Exception as _eval_exc:
            log.error("page.evaluate failed: %s", _eval_exc)
            log.error("Check the JavaScript block in monitor.py for syntax errors")
            raw_projects = []

        log.info("Scraped %d raw project links", len(raw_projects))
        if raw_projects:
            log.info("SUCCESS: extracted %d project URLs", len(raw_projects))

        # ── Python-side title cleanup + category pre-detection ─────────────────
        # Even if JS extracted something, run through Python filter as a safety net
        # (handles edge cases JS might miss, and adds category detection).
        cleaned = []
        for i, p in enumerate(raw_projects):
            title    = p.get("title", "")
            raw_text = p.get("raw_text", "")

            # Python-side title validation/cleanup
            if not title or title == "(بدون عنوان)" or _is_label(title):
                lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
                title = _extract_title_from_lines(lines)

            # Category pre-detection (used as fallback when AI is off)
            category_hint = _detect_category(raw_text, title)

            p["title"]          = title
            p["category_hint"]  = category_hint   # AI will override this if enabled
            cleaned.append(p)

            # Debug logging for first 3 projects only
            if i < 3:
                log.info(
                    "DEBUG card[%d]: url=%s | extracted_title=%r | category_hint=%r\nraw_card_text:\n%s\ncard_html_first1000:\n%s",
                    i,
                    p.get("url", ""),
                    title,
                    category_hint,
                    raw_text,
                    p.get("card_html", ""),
                )

        projects = cleaned
        browser.close()

    return projects


def scrape_projects() -> list[dict]:
    """Scrape with retry logic. Returns empty list after all retries fail."""
    for attempt in range(1, SCRAPE_MAX_RETRIES + 1):
        try:
            return _do_scrape()
        except Exception as exc:
            log.warning("Scrape attempt %d/%d failed: %s", attempt, SCRAPE_MAX_RETRIES, exc)
            if attempt < SCRAPE_MAX_RETRIES:
                log.info("Retrying in %ds …", SCRAPE_RETRY_DELAY_S)
                time.sleep(SCRAPE_RETRY_DELAY_S)
    log.error("All scrape attempts failed. Skipping this run.")
    return []


def scrape_bahr_projects() -> list[dict]:
    """Run the existing Bahr scraper and tag its source."""
    projects = scrape_projects()
    for p in projects:
        p["source"] = "bahr"
    return projects


def scrape_mostaql_projects_for_pipeline() -> list[dict]:
    """Run the standalone Mostaql scraper and normalize fields for this pipeline."""
    try:
        projects = scrape_mostaql_projects()
    except Exception as exc:
        log.warning("Mostaql scrape failed: %s", exc)
        return []

    normalized = []
    for p in projects:
        title = p.get("title", "")
        raw_text = p.get("raw_text", "")
        project = dict(p)
        url = project.get("url", "")
        mostaql_id = url.rstrip("/").split("/project/", 1)[-1].split("-", 1)[0] if "/project/" in url else url
        project["source"] = "mostaql"
        project["id"] = f"mostaql:{mostaql_id}" if mostaql_id else url
        project["description"] = project.get("description_preview", "")
        project["category_hint"] = _detect_category(raw_text, title)
        normalized.append(project)
    return normalized


def _telegram_title(text: str) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= 80:
        return clean or "Telegram opportunity"
    return clean[:77].rstrip() + "..."


def scrape_telegram_projects_for_pipeline() -> list[dict]:
    """Run Telegram scraper if enabled and normalize results for this pipeline."""
    log.info("TELEGRAM_SCRAPER_ENABLED=%s", TELEGRAM_SCRAPER_ENABLED)
    log.info("TELEGRAM_API_ID exists=%s", bool(__import__("os").environ.get("TELEGRAM_API_ID")))
    log.info("TELEGRAM_API_HASH exists=%s", bool(__import__("os").environ.get("TELEGRAM_API_HASH")))
    log.info("TELEGRAM_SESSION_STRING exists=%s", bool(__import__("os").environ.get("TELEGRAM_SESSION_STRING")))
    log.info("TELEGRAM_TARGET_GROUPS=%s", __import__("os").environ.get("TELEGRAM_TARGET_GROUPS", ""))
    if not TELEGRAM_SCRAPER_ENABLED:
        log.info("Telegram scraper disabled.")
        return []

    try:
        opportunities = asyncio.run(scrape_telegram_opportunities())
    except Exception as exc:
        log.warning("Telegram scrape skipped: %s", exc)
        return []

    normalized = []
    for item in opportunities:
        score = int(item.get("opportunity_score") or 0)
        if score < TELEGRAM_MIN_SCORE:
            continue
        group_id = item.get("group_id", "")
        message_id = item.get("message_id", "")
        message_link = item.get("message_link", "")
        message_text = item.get("message_text") or item.get("raw_text", "")
        pid = f"telegram:{group_id}:{message_id}" if group_id and message_id else f"telegram:{message_link}"

        normalized.append({
            "source": "telegram",
            "id": pid,
            "title": _telegram_title(message_text),
            "url": message_link,
            "description": message_text,
            "category": "telegram",
            "category_hint": "telegram",
            "published_at": item.get("message_date", ""),
            "score": score,
            "raw_text": item.get("raw_text") or message_text,
            "group_name": item.get("group_name", ""),
            "sender_name": item.get("sender_name", ""),
            "matched_keywords": item.get("matched_keywords", []),
            "hiring_indicators": item.get("hiring_indicators", []),
            "score_reason": item.get("score_reason", ""),
        })

    return normalized


def _source_for_entry(entry: dict) -> str:
    source = entry.get("source")
    if source:
        return source
    url = entry.get("url", "")
    pid = entry.get("id", "")
    if "telegram:" in pid or "t.me/" in url:
        return "telegram"
    if "mostaql.com" in url or "mostaql.com" in pid:
        return "mostaql"
    return "bahr"


def normalize_seen_sources(db: dict) -> None:
    """Backfill source on legacy seen entries."""
    for entry in db.values():
        if isinstance(entry, dict) and not entry.get("source"):
            entry["source"] = _source_for_entry(entry)


def is_seen_by_source(project: dict, db: dict) -> tuple[bool, str]:
    """Source-aware duplicate check without changing storage.py."""
    source = project.get("source", "bahr")
    pid = project.get("id", "")
    url = project.get("url", "")
    title = project.get("title", "").strip()

    if pid and pid in db:
        entry = db[pid]
        if _source_for_entry(entry) == source:
            return True, f"{source} ID '{pid}' already seen on {entry.get('first_seen', '?')}"

    if url:
        for entry in db.values():
            if _source_for_entry(entry) == source and entry.get("url") == url:
                return True, f"{source} URL already seen (entry: {entry.get('id', '?')})"

    if title and len(title) > 10:
        for entry in db.values():
            if _source_for_entry(entry) == source and entry.get("title", "").strip() == title:
                return True, f"{source} title already seen (entry: {entry.get('id', '?')})"

    return False, ""


def mark_seen_by_source(project: dict, db: dict, notification_sent: bool = False) -> None:
    """Mark seen and persist source metadata in the existing seen DB shape."""
    mark_seen(project, db, notification_sent=notification_sent)
    pid = project.get("id", project.get("url", "unknown"))
    db.setdefault(pid, {})["source"] = project.get("source", "bahr")


# ─── Filtering helpers ────────────────────────────────────────────────────────

def matches_keywords(project: dict) -> bool:
    if project.get("source") == "telegram" and int(project.get("score") or 0) >= TELEGRAM_MIN_SCORE:
        return True
    haystack = (project.get("title", "") + " " + project.get("raw_text", "")).lower()
    return any(kw.lower() in haystack for kw in KEYWORDS)


def keyword_score(project: dict) -> float:
    haystack = (project.get("title", "") + " " + project.get("raw_text", "")).lower()
    matched  = sum(1 for kw in KEYWORDS if kw.lower() in haystack)
    return min(matched / max(len(KEYWORDS), 1), 1.0)


_LEVEL_MAP = {"low": 0.2, "medium": 0.5, "high": 0.9}


def compute_composite_score(
    project: dict,
    analysis: dict,
    profile_match_score: float = 0.5,
    preference_boost: float = 0.5,
) -> float:
    """Weighted composite score 0–100. Extended from v2."""
    ai_score   = analysis.get("score", 50) / 100.0
    kw_score   = keyword_score(project)
    profit     = _LEVEL_MAP.get(analysis.get("profitability", "medium"), 0.5)
    urgency    = _LEVEL_MAP.get(analysis.get("urgency", "low"), 0.2)

    w = SCORE_WEIGHTS
    composite = (
        ai_score           * w["ai_score"]          +
        kw_score           * w["keyword_relevance"]  +
        profit             * w["profitability"]      +
        urgency            * w["urgency"]            +
        profile_match_score * w.get("profile_match", 0.15) +
        preference_boost    * w.get("preference_boost", 0.10)
    )
    return round(composite * 100, 1)


def is_golden_opportunity(
    composite_score: float,
    analysis: dict,
    win_prob_result: dict,
) -> bool:
    """
    Classify a project as a Golden Opportunity.
    Must meet ALL thresholds simultaneously.
    """
    if composite_score < GOLDEN_MIN_SCORE:
        return False
    if win_prob_result.get("probability", 0) < GOLDEN_MIN_WIN_PCT:
        return False
    if GOLDEN_PROFITABILITY == "high" and analysis.get("profitability") != "high":
        return False
    return True


# ─── Main pipeline ────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Opportunity Monitor Started ===")
    log.info("═══ Bahr Monitor v3 — run started %s ═══", datetime.now().isoformat())

    # 0. Initialize DB
    init_db()

    # 1. Load seen-projects database (dedup)
    seen_db = load_seen_db()
    normalize_seen_sources(seen_db)
    log.info("Loaded %d previously seen projects", len(seen_db))
    log.info("Preference engine: %s", get_preference_summary())

    # 2. Scrape sources
    bahr_projects = scrape_bahr_projects()
    log.info("Bahr projects found: %d", len(bahr_projects))
    mostaql_projects = scrape_mostaql_projects_for_pipeline()
    log.info("Mostaql projects found: %d", len(mostaql_projects))
    telegram_projects = scrape_telegram_projects_for_pipeline()
    log.info("Telegram projects found: %d", len(telegram_projects))
    all_projects = bahr_projects + mostaql_projects + telegram_projects
    log.info("Total opportunities collected: %d", len(all_projects))
    log.info(
        "Projects found: Bahr: %d | Mostaql: %d | Telegram: %d | Total: %d",
        len(bahr_projects),
        len(mostaql_projects),
        len(telegram_projects),
        len(all_projects),
    )
    log.info("Scraped %d total projects", len(all_projects))

    if not all_projects:
        log.warning("No projects found this run.")
        log.info("No new opportunities found. Email not sent.")
        log.info("=== Opportunity Monitor Finished ===")
        return

    # 3. De-duplicate
    new_projects = []
    for p in all_projects:
        seen, reason = is_seen_by_source(p, seen_db)
        if seen:
            log.debug(
                "SKIP (already seen): [%s] %s — %s",
                p.get("source", "bahr"),
                p.get("title", "")[:50],
                reason,
            )
        else:
            new_projects.append(p)

    log.info("New (unseen) projects: %d", len(new_projects))
    previously_seen = len(all_projects) - len(new_projects)
    log.info("New opportunities: %d", len(new_projects))
    log.info("Previously seen opportunities: %d", previously_seen)

    # 4. Keyword filter
    matched = [p for p in new_projects if matches_keywords(p)]
    log.info("Keyword-matched new projects: %d", len(matched))

    # 5. Mark ALL new projects seen NOW (prevents re-checking regardless of match)
    for p in new_projects:
        mark_seen_by_source(p, seen_db, notification_sent=False)

    if not matched:
        log.info("No keyword-matched new projects — no notifications sent.")
        log.info("No new opportunities found. Email not sent.")
        save_seen_db(seen_db)
        log.info("═══ Run complete ═══")
        log.info("=== Opportunity Monitor Finished ===")
        return

    # 6. Load project history for similarity checks
    project_history = get_all_projects(limit=500)
    log.info("Loaded %d historical projects for similarity.", len(project_history))

    # 7. Full analysis pipeline per project
    enriched: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for p in matched:
        log.info("Analyzing: %s", p.get("title", "")[:60])
        p["_discovered_at"] = now_iso   # inject for win probability age calculation

        # AI analysis (with retry, profile-aware)
        analysis = analyze_project(p)

        # Real win probability engine
        win_prob_result = compute_win_probability(p, analysis)

        # Profile matching
        prof_match = compute_profile_match(p)
        prof_score = prof_match["score"] / 100.0

        # Personal preference boost
        pref_boost = compute_preference_boost(p, analysis.get("category", ""))

        # Composite score (now includes profile + preference)
        composite = compute_composite_score(p, analysis, prof_score, pref_boost)

        # Auto-learn from high scorers
        if composite >= 75:
            auto_learn_from_high_scores(p, composite, analysis.get("category", ""))

        # Proposal generation
        proposal = generate_proposal(p)

        # Similarity check against history
        sim_result = find_similar_projects(p, project_history, threshold=SIMILARITY_THRESHOLD)

        # Golden opportunity classification
        golden = is_golden_opportunity(composite, analysis, win_prob_result)

        enriched.append({
            "project":          p,
            "analysis":         analysis,
            "proposal":         proposal,
            "composite":        composite,
            "win_prob_result":  win_prob_result,
            "profile_match":    prof_match,
            "preference_boost": pref_boost,
            "similarity_result": sim_result,
            "is_golden":        golden,
        })

    # 8. Sort: golden first, then by composite score
    enriched.sort(key=lambda ep: (not ep["is_golden"], -ep["composite"]))
    log.info(
        "Projects ranked: top=%.1f, golden=%d, high=%d",
        enriched[0]["composite"] if enriched else 0,
        sum(1 for ep in enriched if ep["is_golden"]),
        sum(1 for ep in enriched if ep["composite"] >= HIGH_PRIORITY_SCORE),
    )

    # 9. Notifications — tiered
    golden_count = 0
    for ep in enriched:
        notify_project(
            ep["project"],
            ep["analysis"],
            ep["proposal"],
            win_prob_result=ep["win_prob_result"],
            is_golden=ep["is_golden"],
            similarity_result=ep["similarity_result"],
        )
        if ep["is_golden"]:
            send_golden_alert(ep["project"], ep["analysis"], ep["win_prob_result"], ep["proposal"])
            golden_count += 1

        mark_seen_by_source(ep["project"], seen_db, notification_sent=True)

    # 10. Email digest
    log.info("Preparing email report...")
    try:
        send_email(enriched)
        if EMAIL_ENABLED and all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
            log.info("Email sent successfully to: %s", EMAIL_RECEIVER)
    except Exception as exc:
        log.exception("Email sending failed: %s", exc)
        raise

    # 11. Persist to SQLite history
    for ep in enriched:
        sim_ids = [s["id"] for s in ep["similarity_result"].get("similar_projects", [])]
        upsert_project(
            project=ep["project"],
            analysis=ep["analysis"],
            proposal=ep["proposal"],
            composite_score=ep["composite"],
            win_prob_result=ep["win_prob_result"],
            is_golden=ep["is_golden"],
            similarity_ids=sim_ids,
        )

    # 12. Save dedup DB
    save_seen_db(seen_db)

    # 13. Weekly market intelligence report
    if is_market_report_day():
        log.info("Generating weekly market intelligence report …")
        try:
            all_projects_db = get_all_projects(limit=2000)
            report = build_market_report(all_projects_db)
            save_market_report(report)
            tg_market_report(format_market_report_telegram(report))
            # Inject into next email if same run (edge case)
        except Exception as exc:
            log.error("Market report generation failed: %s", exc)

    # 14. Summary
    stats = get_stats()
    log.info(
        "═══ Run complete — new=%d, matched=%d, golden=%d | DB total=%d ═══",
        len(new_projects), len(matched), golden_count, stats.get("total_projects", 0)
    )
    log.info("=== Opportunity Monitor Finished ===")


if __name__ == "__main__":
    main()
