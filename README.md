# 🌊 Bahr Monitor v2 — Smart Project Discovery System

A fully automated system that monitors **bahr.sa** every 15 minutes for new freelance
projects, analyzes them with AI, generates Arabic proposals, and alerts you instantly
via Telegram and email — **without ever sending duplicate notifications**.

---

## ✨ Features

| Feature | Details |
|---|---|
| ⏱ **15-minute monitoring** | GitHub Actions cron job, reliable and free |
| 🔒 **Zero duplicate alerts** | Multi-layer deduplication by ID, URL, and title |
| 🤖 **AI analysis** | Score, category, skills, win chance, profitability, urgency |
| ✍️ **Auto proposals** | Professional Arabic proposals, ready to copy-paste |
| 📊 **Smart ranking** | Projects sorted by composite opportunity score |
| 📱 **Telegram alerts** | Instant notifications for high-scoring projects |
| 📧 **HTML email digest** | Color-coded project cards with full AI analysis |
| 🔧 **Configurable** | Keywords, thresholds, profile — all via env vars |

---

## 📁 Project Structure

```
bahr_monitor/
├── monitor.py              # Main orchestrator
├── config.py               # All configuration
├── storage.py              # De-duplication & persistence
├── ai_analyzer.py          # AI-powered project analysis
├── proposal_generator.py   # Arabic proposal generation
├── notifier_email.py       # HTML email digest
├── notifier_telegram.py    # Instant Telegram notifications
├── requirements.txt
├── .env.example            # Copy to .env for local use
├── .gitignore
├── seen_ids.json           # Auto-managed dedup database (committed by CI)
└── .github/
    └── workflows/
        └── bahr_monitor.yml
```

---

## 🚀 Quick Start

### Local Installation

```bash
git clone https://github.com/YOUR_USERNAME/bahr-monitor.git
cd bahr-monitor

pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# Edit .env with your credentials

python monitor.py
```

### GitHub Actions Setup

1. Push this repository to GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Add the secrets listed in the table below.
4. The workflow runs automatically every 15 minutes.

---

## 🔑 Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `EMAIL_ENABLED` | No | `true` | Enable email digest |
| `EMAIL_SENDER` | If email | — | Gmail sender address |
| `EMAIL_PASSWORD` | If email | — | Gmail App Password |
| `EMAIL_RECEIVER` | If email | — | Recipient address |
| `TELEGRAM_ENABLED` | No | `false` | Enable Telegram alerts |
| `TELEGRAM_BOT_TOKEN` | If TG | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | If TG | — | Your chat ID |
| `AI_ENABLED` | No | `false` | Enable AI analysis |
| `AI_PROVIDER` | No | `openai` | `openai` or `anthropic` |
| `OPENAI_API_KEY` | If AI | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | If AI | — | Anthropic API key |
| `AI_MODEL` | No | `gpt-4o-mini` | Model to use |
| `MIN_NOTIFY_SCORE` | No | `60` | Minimum score for Telegram |
| `MAX_SCROLL_STEPS` | No | `8` | Scroll depth on bahr.sa |
| `PROFILE_NAME` | No | `مبارك` | Your name for proposals |
| `PROFILE_SKILLS` | No | *(see .env.example)* | Your skills |
| `PROFILE_EXPERIENCE` | No | `5+ سنوات` | Your experience |

---

## 📱 Telegram Setup

1. Message **@BotFather** → `/newbot` → copy the token.
2. Message **@userinfobot** to get your chat ID.
3. Set `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`.
4. Set `MIN_NOTIFY_SCORE` (0–100) — only projects above this score trigger alerts.

---

## 🤖 AI Analysis

When `AI_ENABLED=true`, every new keyword-matching project gets:

- **Summary** — concise Arabic description
- **Category** — e.g., تصميم جرافيك, تطوير ويب
- **Skills** — recommended skills list
- **Score (0–100)** — how well it matches your profile
- **Win chance** — low / medium / high
- **Profitability** — low / medium / high
- **Urgency** — low / medium / high
- **Recommendation** — Apply / Consider / Skip

Works with **OpenAI** (gpt-4o-mini recommended) or **Anthropic** (claude-haiku).

---

## 🔒 Duplicate Prevention Strategy

The system uses three layers of deduplication:

1. **ID check** — project href/path used as stable ID
2. **URL check** — catches ID format changes
3. **Title check** — catches restructured pages (for titles > 10 chars)

The `seen_ids.json` stores full metadata (first seen date, notification date) and
is committed back to the repo after every run — ensuring deduplication persists
even across job restarts or cache evictions.

**Old format migration:** If you have the legacy `seen_ids.json` (plain list),
it will be automatically migrated on the first run.

---

## 📊 Ranking

Projects are ranked by a weighted composite score:

| Factor | Weight |
|---|---|
| AI suitability score | 40% |
| Keyword relevance | 25% |
| Profitability estimate | 20% |
| Urgency level | 15% |

---

## ⚠️ Important Constraints

This system only:
- **Monitors** bahr.sa for new projects
- **Analyzes** and ranks them
- **Generates** proposal drafts
- **Notifies** you via Telegram/email

It does **NOT** submit proposals automatically. All action is manual.

---

## 🔧 Keyword Customization

Edit `KEYWORDS` in `config.py` or override via environment. Current defaults:

```
تصوير، مونتاج، موشن، تصميم، فيديو، موقع، برمجة،
ذكاء اصطناعي، أتمتة، إعلان، هوية بصرية، محتوى،
سوشال ميديا، جرافيك، شات بوت، متجر إلكتروني،
تطبيق، بايثون، API، تحليل بيانات، automation، AI
```
