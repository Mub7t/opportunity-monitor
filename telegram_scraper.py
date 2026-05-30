"""
Standalone Telegram opportunity scraper.

Run:
    python3 telegram_scraper.py

Environment:
    TELEGRAM_API_ID       required
    TELEGRAM_API_HASH     required
    TELEGRAM_PHONE        required on first login
    TELEGRAM_TARGET_GROUPS optional comma-separated usernames or titles
"""

import asyncio
import html
import json
import logging
import os
import smtplib
from datetime import timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience only
    load_dotenv = None

try:
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError
    from telethon.tl.types import Channel, Chat, User
except ImportError as exc:  # pragma: no cover - handled in main
    TelegramClient = None
    FloodWaitError = None
    Channel = Chat = User = None
    TELETHON_IMPORT_ERROR = exc
else:
    TELETHON_IMPORT_ERROR = None


if load_dotenv:
    load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


SESSION_NAME = os.environ.get("TELEGRAM_SESSION_FILE", "telegram_scraper")
CONFIG_FILE = Path(os.environ.get("TELEGRAM_SCRAPER_CONFIG", "telegram_scraper_config.json"))
OPPORTUNITIES_FILE = Path(os.environ.get("TELEGRAM_OPPORTUNITIES_FILE", "telegram_opportunities.json"))
MAX_JSON_OPPORTUNITIES = 50
MESSAGE_LIMIT = int(os.environ.get("TELEGRAM_MESSAGE_LIMIT") or "200")
MESSAGE_LIMIT = max(1, min(MESSAGE_LIMIT, 500))
RATE_LIMIT_SECONDS = float(os.environ.get("TELEGRAM_RATE_LIMIT_SECONDS") or "1.5")
MIN_OPPORTUNITY_SCORE = int(os.environ.get("TELEGRAM_MIN_OPPORTUNITY_SCORE") or "80")
TARGET_GROUPS = [
    item.strip()
    for item in os.environ.get("TELEGRAM_TARGET_GROUPS", "").split(",")
    if item.strip()
]


OPPORTUNITY_KEYWORDS = [
    "مطلوب مصور",
    "مطلوب مونتير",
    "نحتاج مصور",
    "نحتاج مونتاج",
    "تصوير فعالية",
    "تغطية فعالية",
    "تصوير زواج",
    "تصوير منتجات",
    "موشن جرافيك",
    "تصميم فيديو",
    "إعلان",
    "سوشال ميديا",
    "مصمم",
    "مونتاج",
    "تصوير",
]


HIRING_INDICATORS = [
    "مطلوب",
    "نحتاج",
    "ابحث عن",
    "أبحث عن",
    "نبحث عن",
    "احتاج",
    "أحتاج",
    "hiring",
    "looking for",
    "مطلوب مصور",
    "مطلوب مونتير",
    "نبحث عن مصمم",
    "مطلوب تغطية",
    "فرصة عمل",
]


STRONG_HIRING_INDICATORS = [
    "مطلوب مصور",
    "مطلوب مونتير",
    "نحتاج مصور",
    "نحتاج مونتاج",
    "نبحث عن مصمم",
    "مطلوب تغطية",
    "فرصة عمل",
]


DOWNRANK_INDICATORS = [
    "عندي خدمة",
    "أقدم خدمة",
    "اقدم خدمة",
    "أعمالي",
    "اعمالي",
    "معرض أعمال",
    "معرض اعمالي",
    "بكج",
    "للتواصل",
    "خدماتي",
    "هذا عملي",
    "للبيع",
    "متوفر للتصوير",
    "متوفر مونتاج",
    "احجز",
    "خصم",
    "عرض خاص",
]


DOMAIN_KEYWORDS = [
    "مصور",
    "مونتير",
    "مصمم",
    "تصوير",
    "مونتاج",
    "موشن",
    "موشن جرافيك",
    "تصميم",
    "فيديو",
    "إعلان",
    "اعلان",
    "سوشال ميديا",
    "تغطية",
    "photographer",
    "videographer",
    "video editor",
    "designer",
    "motion graphics",
]


def _env_int(name: str) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


def _env_str(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _clean_text(text: str | None) -> str:
    return " ".join((text or "").split())


def _load_saved_targets() -> list[str]:
    if not CONFIG_FILE.exists():
        return []
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read %s: %s", CONFIG_FILE, exc)
        return []
    targets = data.get("target_groups", [])
    return [str(item).strip() for item in targets if str(item).strip()]


def _save_targets(entities: list) -> None:
    targets = []
    for entity in entities:
        username = getattr(entity, "username", None)
        targets.append(f"@{username}" if username else _entity_name(entity))
    data = {"target_groups": targets}
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Saved %d Telegram targets to %s", len(targets), CONFIG_FILE)


def _entity_name(entity) -> str:
    title = getattr(entity, "title", None)
    if title:
        return title
    if isinstance(entity, User):
        parts = [entity.first_name or "", entity.last_name or ""]
        return " ".join(p for p in parts if p).strip() or str(entity.id)
    return str(getattr(entity, "id", "unknown"))


def _sender_name(sender) -> str:
    if not sender:
        return ""
    if isinstance(sender, User):
        parts = [sender.first_name or "", sender.last_name or ""]
        return " ".join(p for p in parts if p).strip() or (sender.username or "")
    return getattr(sender, "title", "") or getattr(sender, "username", "") or ""


def _message_link(entity, message_id: int) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    if isinstance(entity, Channel):
        return f"https://t.me/c/{entity.id}/{message_id}"
    return ""


def _matched_keywords(text: str) -> list[str]:
    lowered = text.lower()
    return [kw for kw in OPPORTUNITY_KEYWORDS if kw.lower() in lowered]


def _score_message(text: str) -> dict:
    clean = _clean_text(text)
    lowered = clean.lower()
    matched_keywords = [kw for kw in OPPORTUNITY_KEYWORDS if kw.lower() in lowered]
    hiring = [kw for kw in HIRING_INDICATORS if kw.lower() in lowered]
    strong_hiring = [kw for kw in STRONG_HIRING_INDICATORS if kw.lower() in lowered]
    negatives = [kw for kw in DOWNRANK_INDICATORS if kw.lower() in lowered]
    domains = [kw for kw in DOMAIN_KEYWORDS if kw.lower() in lowered]

    score = 0
    reasons = []

    if strong_hiring:
        score += 55
        reasons.append("strong hiring phrase")
    elif hiring:
        score += 40
        reasons.append("hiring intent")

    if domains:
        score += 25
        reasons.append("creative/media domain")

    if hiring and domains:
        score += 20
        reasons.append("request + relevant skill")

    if any(term in lowered for term in ("ميزانية", "الميزانية", "راتب", "أجر", "اجر", "مقابل")):
        score += 10
        reasons.append("mentions payment/budget")

    if any(term in lowered for term in ("خاص", "dm", "تواصل معي", "يرسل", "ارسال العرض")) and hiring:
        score += 5
        reasons.append("asks for contact/proposal")

    if negatives:
        score -= 20 if hiring else 45
        reasons.append("service/ad language")

    if domains and not hiring:
        score = min(score, 45)
        reasons.append("domain mention without hiring intent")

    if negatives and not hiring:
        score = min(score, 25)

    score = max(0, min(100, score))
    if not reasons:
        reasons.append("no hiring intent")

    return {
        "score": score,
        "matched_keywords": matched_keywords,
        "matched_hiring_indicators": hiring,
        "negative_indicators": negatives,
        "reason": "; ".join(reasons),
    }


async def _list_candidate_dialogs(client) -> list:
    dialogs = []
    async for dialog in client.iter_dialogs(limit=200):
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            dialogs.append(entity)
    return dialogs


async def _resolve_targets(client, target_names: list[str]) -> list:
    dialogs = await _list_candidate_dialogs(client)
    by_title = {_entity_name(entity).strip().lower(): entity for entity in dialogs}
    by_username = {
        ("@" + entity.username.lower()): entity
        for entity in dialogs
        if getattr(entity, "username", None)
    }
    by_username.update({
        entity.username.lower(): entity
        for entity in dialogs
        if getattr(entity, "username", None)
    })

    if not target_names:
        saved_targets = _load_saved_targets()
        if saved_targets:
            target_names = saved_targets

    should_save_selection = False
    if not target_names:
        print("No TELEGRAM_TARGET_GROUPS configured.")
        print("Available groups/channels:")
        for i, entity in enumerate(dialogs[:80], start=1):
            username = getattr(entity, "username", None)
            handle = f"@{username}" if username else ""
            print(f"{i:>2}. {_entity_name(entity)} {handle}")
        raw = input("Enter target numbers, usernames, or exact titles separated by commas: ").strip()
        target_names = [item.strip() for item in raw.split(",") if item.strip()]
        should_save_selection = True

    resolved = []
    seen_ids = set()
    for target in target_names:
        entity = None
        key = target.strip().lower()

        if key.isdigit():
            index = int(key) - 1
            if 0 <= index < len(dialogs):
                entity = dialogs[index]
        if entity is None:
            entity = by_username.get(key) or by_title.get(key)
        if entity is None:
            try:
                entity = await client.get_entity(target)
            except Exception as exc:
                log.warning("Could not resolve Telegram target %r: %s", target, exc)
                continue

        entity_id = getattr(entity, "id", None)
        if entity_id not in seen_ids:
            resolved.append(entity)
            seen_ids.add(entity_id)

    if should_save_selection and resolved:
        _save_targets(resolved)

    return resolved


async def scrape_telegram_opportunities(
    target_groups: list[str] | None = None,
    limit: int = MESSAGE_LIMIT,
) -> list[dict]:
    """Read recent messages from configured Telegram groups/channels."""
    if TELETHON_IMPORT_ERROR:
        raise RuntimeError(
            "Telethon is not installed. Install it with: pip install telethon"
        ) from TELETHON_IMPORT_ERROR

    api_id = _env_int("TELEGRAM_API_ID")
    api_hash = _env_str("TELEGRAM_API_HASH")
    phone = os.environ.get("TELEGRAM_PHONE", "").strip() or None

    client = TelegramClient(SESSION_NAME, api_id, api_hash)
    await client.start(phone=phone)

    try:
        targets = await _resolve_targets(client, target_groups or TARGET_GROUPS)
        results = []
        seen_messages = set()
        messages_scanned = 0

        for entity in targets:
            group_name = _entity_name(entity)
            group_id = getattr(entity, "id", "")
            log.info("Scanning %s", group_name)

            try:
                async for message in client.iter_messages(entity, limit=limit):
                    messages_scanned += 1
                    message_text = message.message or ""
                    if not message_text.strip():
                        continue

                    dedupe_key = f"{group_id}:{message.id}"
                    if dedupe_key in seen_messages:
                        continue
                    seen_messages.add(dedupe_key)

                    scoring = _score_message(message_text)
                    if scoring["score"] < MIN_OPPORTUNITY_SCORE:
                        continue

                    sender = await message.get_sender()
                    date = message.date
                    if date and date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)

                    results.append({
                        "source": "telegram",
                        "group_id": group_id,
                        "message_id": message.id,
                        "group_name": group_name,
                        "sender_name": _sender_name(sender),
                        "message_text": message_text,
                        "message_date": date.isoformat() if date else "",
                        "message_link": _message_link(entity, message.id),
                        "matched_keywords": scoring["matched_keywords"],
                        "hiring_indicators": scoring["matched_hiring_indicators"],
                        "negative_indicators": scoring["negative_indicators"],
                        "opportunity_score": scoring["score"],
                        "score_reason": scoring["reason"],
                        "raw_text": message_text,
                    })

                await asyncio.sleep(RATE_LIMIT_SECONDS)

            except FloodWaitError as exc:
                wait_seconds = int(getattr(exc, "seconds", 60))
                log.warning("Telegram rate limit for %s. Waiting %ss", group_name, wait_seconds)
                await asyncio.sleep(wait_seconds)

        results.sort(key=lambda item: item.get("opportunity_score", 0), reverse=True)
        scrape_telegram_opportunities.groups_scanned = len(targets)
        scrape_telegram_opportunities.messages_scanned = messages_scanned
        return results

    finally:
        await client.disconnect()


def _print_results(results: list[dict]) -> None:
    groups_scanned = getattr(scrape_telegram_opportunities, "groups_scanned", 0)
    messages_scanned = getattr(scrape_telegram_opportunities, "messages_scanned", 0)

    print(f"Groups scanned: {groups_scanned}")
    print(f"Messages scanned: {messages_scanned}")
    print(f"High-quality opportunities found: {len(results)}")
    print(f"Saved to {OPPORTUNITIES_FILE}")
    print("Top 20 opportunities:")
    print("=" * 80)

    for i, item in enumerate(results[:20], start=1):
        print(f"{i}. {item['group_name']} | score={item['opportunity_score']}/100")
        print(f"   Sender: {item['sender_name'] or 'N/A'}")
        print(f"   Date: {item['message_date']}")
        print(f"   Link: {item['message_link'] or 'N/A'}")
        print(f"   Matched keywords: {', '.join(item['matched_keywords']) or 'N/A'}")
        print(f"   Hiring indicators: {', '.join(item['hiring_indicators']) or 'N/A'}")
        print(f"   Reason: {item['score_reason']}")
        print(f"   Text: {_clean_text(item['message_text'])[:700]}")
        print("-" * 80)


def _email_enabled() -> bool:
    return os.environ.get("EMAIL_ENABLED", "true").lower() == "true"


def _build_email_body(results: list[dict]) -> str:
    groups_scanned = getattr(scrape_telegram_opportunities, "groups_scanned", 0)
    messages_scanned = getattr(scrape_telegram_opportunities, "messages_scanned", 0)
    items = []

    for item in results[:20]:
        link = item.get("message_link", "")
        link_html = (
            f'<p><a href="{html.escape(link)}">Open message</a></p>'
            if link else ""
        )
        items.append(f"""
        <li style="margin-bottom:18px">
          <b>{html.escape(item.get("group_name", ""))}</b>
          <span style="color:#555">score {int(item.get("opportunity_score", 0))}/100</span><br>
          <small>{html.escape(item.get("message_date", ""))}</small><br>
          <b>Matched:</b> {html.escape(", ".join(item.get("matched_keywords", [])) or "N/A")}<br>
          <p>{html.escape(_clean_text(item.get("message_text", ""))[:500])}</p>
          {link_html}
        </li>
        """)

    return f"""
    <html>
      <body dir="rtl" style="font-family:Arial,sans-serif;line-height:1.6">
        <h2>Telegram Opportunities Report</h2>
        <p><b>Groups scanned:</b> {groups_scanned}</p>
        <p><b>Messages scanned:</b> {messages_scanned}</p>
        <p><b>Opportunities found:</b> {len(results)}</p>
        <h3>Top 20 opportunities</h3>
        <ol>
          {''.join(items)}
        </ol>
      </body>
    </html>
    """


def _send_email_report(results: list[dict]) -> bool:
    if not results:
        return False
    if not _email_enabled():
        log.info("Email disabled; skipping Telegram report.")
        return False

    sender = os.environ.get("EMAIL_SENDER", "").strip()
    password = os.environ.get("EMAIL_PASSWORD", "").strip()
    receiver = os.environ.get("EMAIL_RECEIVER", "").strip()
    if not (sender and password and receiver):
        log.warning("Email credentials missing; skipping Telegram report.")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = "Telegram Opportunities Report"
    msg.attach(MIMEText(_build_email_body(results), "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [receiver], msg.as_string())
    return True


async def _main() -> None:
    results = await scrape_telegram_opportunities()
    results = results[:MAX_JSON_OPPORTUNITIES]
    OPPORTUNITIES_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not results:
        groups_scanned = getattr(scrape_telegram_opportunities, "groups_scanned", 0)
        messages_scanned = getattr(scrape_telegram_opportunities, "messages_scanned", 0)
        print(f"Groups scanned: {groups_scanned}")
        print(f"Messages scanned: {messages_scanned}")
        print("High-quality opportunities found: 0")
        print(f"Saved to {OPPORTUNITIES_FILE}")
        print("No high-quality Telegram opportunities found.")
        return

    _print_results(results)
    if _send_email_report(results):
        print("Email sent successfully")


if __name__ == "__main__":
    asyncio.run(_main())
