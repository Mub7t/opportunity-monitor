"""
Standalone Telegram opportunity scraper.

Run:
    python3 telegram_scraper.py

Environment:
    TELEGRAM_API_ID       33933615
    TELEGRAM_API_HASH     11742ebdba4630e65
    TELEGRAM_PHONE=966512345678
    TELEGRAM_TARGET_GROUPS optional comma-separated usernames or titles
"""

import asyncio
import logging
import os
from datetime import timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience only
    load_dotenv = None

try:
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError
    from telethon.sessions import StringSession
    from telethon.tl.types import Channel, Chat, User
except ImportError as exc:  # pragma: no cover - handled in main
    TelegramClient = None
    FloodWaitError = None
    StringSession = None
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
MESSAGE_LIMIT = int(os.environ.get("TELEGRAM_MESSAGE_LIMIT") or "200")
MESSAGE_LIMIT = max(1, min(MESSAGE_LIMIT, 500))
RATE_LIMIT_SECONDS = float(os.environ.get("TELEGRAM_RATE_LIMIT_SECONDS") or "1.5")
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


def _session_file_exists() -> bool:
    session_path = Path(SESSION_NAME)
    if session_path.exists():
        return True
    if session_path.suffix != ".session":
        return session_path.with_suffix(".session").exists()
    return False


async def _create_authorized_client(api_id: int, api_hash: str):
    session_string = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
    session_string_exists = bool(session_string)
    session_file_exists = _session_file_exists()

    if session_string_exists:
        auth_method = "string_session"
        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        log.info("session_string_exists=%s", True)
        log.info("session_file_exists=%s", session_file_exists)
        log.info("using_auth_method=%s", auth_method)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError("TELEGRAM_SESSION_STRING is not authorized")
        return client

    if session_file_exists:
        auth_method = "session_file"
        client = TelegramClient(SESSION_NAME, api_id, api_hash)
        log.info("session_string_exists=%s", False)
        log.info("session_file_exists=%s", True)
        log.info("using_auth_method=%s", auth_method)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError("Local Telegram session file exists but is not authorized")
        return client

    auth_method = "phone"
    phone = _env_str("TELEGRAM_PHONE")
    client = TelegramClient(SESSION_NAME, api_id, api_hash)
    log.info("session_string_exists=%s", False)
    log.info("session_file_exists=%s", False)
    log.info("using_auth_method=%s", auth_method)
    await client.start(phone=phone)
    return client


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
        print("No TELEGRAM_TARGET_GROUPS configured.")
        print("Available groups/channels:")
        for i, entity in enumerate(dialogs[:80], start=1):
            username = getattr(entity, "username", None)
            handle = f"@{username}" if username else ""
            print(f"{i:>2}. {_entity_name(entity)} {handle}")
        raw = input("Enter target numbers, usernames, or exact titles separated by commas: ").strip()
        target_names = [item.strip() for item in raw.split(",") if item.strip()]

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

    client = await _create_authorized_client(api_id, api_hash)

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

                    matches = _matched_keywords(message_text)
                    if not matches:
                        continue

                    sender = await message.get_sender()
                    date = message.date
                    if date and date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)

                    results.append({
                        "source": "telegram",
                        "group_name": group_name,
                        "sender_name": _sender_name(sender),
                        "message_text": message_text,
                        "message_date": date.isoformat() if date else "",
                        "message_link": _message_link(entity, message.id),
                        "matched_keywords": matches,
                        "raw_text": message_text,
                    })

                await asyncio.sleep(RATE_LIMIT_SECONDS)

            except FloodWaitError as exc:
                wait_seconds = int(getattr(exc, "seconds", 60))
                log.warning("Telegram rate limit for %s. Waiting %ss", group_name, wait_seconds)
                await asyncio.sleep(wait_seconds)

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
    print(f"Opportunities found: {len(results)}")
    print("=" * 80)

    for i, item in enumerate(results[:10], start=1):
        print(f"{i}. {item['group_name']}")
        print(f"   Sender: {item['sender_name'] or 'N/A'}")
        print(f"   Date: {item['message_date']}")
        print(f"   Link: {item['message_link'] or 'N/A'}")
        print(f"   Matched: {', '.join(item['matched_keywords'])}")
        print(f"   Text: {_clean_text(item['message_text'])[:700]}")
        print("-" * 80)


async def _main() -> None:
    results = await scrape_telegram_opportunities()
    _print_results(results)


if __name__ == "__main__":
    asyncio.run(_main())
