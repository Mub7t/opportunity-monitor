# Reset Local Test Data & Re-scrape Cleanly

After applying the v3 scraping fix, old corrupted data (wrong titles) must be
removed before re-running. Follow these steps exactly.

---

## Step 1 — Reset all persistent data files

Run from inside your `bahr_monitor_v3/` directory:

```bash
# 1a. Clear the deduplication database (forces re-discovery of all projects)
echo '{}' > seen_ids.json

# 1b. Delete and recreate the SQLite project history database
rm -f projects.db

# 1c. Clear the preference/learning data (optional — keeps your preferences)
# Only run this if you want a truly fresh start:
echo '{}' > preferences.json

# 1d. Clear the market report (it will regenerate on next Monday)
echo '{}' > market_report.json
```

---

## Step 2 — Re-run the monitor

```bash
python monitor.py
```

Watch the log output. You should see lines like:

```
DEBUG card[0]: title='تصميم هوية بصرية لشركة ناشئة' | category_hint='هوية بصرية' | raw_text_first200='بالمشروع↵عن بعد↵مفتوح↵تصميم هوية بصرية...'
DEBUG card[1]: title='موقع إلكتروني لمتجر ملابس' | category_hint='تطوير مواقع' | raw_text_first200='شهري↵...
```

If `title=` shows real project descriptions (not "شهري" or "بالمشروع"), the fix is working.

---

## Step 3 — Verify in the dashboard

```bash
python dashboard.py
```

Open http://localhost:5000 — project cards should now show real titles.

---

## One-liner reset (all in one command)

```bash
echo '{}' > seen_ids.json && rm -f projects.db && echo '{}' > market_report.json && python monitor.py
```

---

## What changed in v3 (this fix)

| File | Change |
|---|---|
| `monitor.py` | Added `_is_label()`, `_extract_title_from_lines()`, `_detect_category()` helpers. JS scraper now tries semantic selectors (h2/h3/[class*="title"]) first, then filters known badge labels from text lines. Python safety-net validates JS result. First 3 cards logged at DEBUG level. |
| `ai_analyzer.py` | `_default_analysis()` now uses `category_hint` from scraper as fallback. AI result category_hint override if AI returns "غير محدد". |

---

## If titles are still wrong after the fix

The `DEBUG card[N]` lines show exactly what the scraper sees. Check:

1. What does `raw_text_first200` contain? Does your card order differ from what's expected?
2. If bahr.sa changed their HTML, the semantic selectors (`h2`, `[class*="title"]`) may need updating.
3. Share the `raw_text_first200` output and the fix can be tuned to match the exact structure.
