"""
login_telegram.py — create a fresh authorized Telethon StringSession.

This script is read-only. It only logs in the current Telegram user account and
prints a session string that can be copied into TELEGRAM_SESSION_STRING.
"""

import asyncio
import logging
import os
import sys
from getpass import getpass

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


logging.disable(logging.CRITICAL)
load_dotenv()


def _stderr_prompt(prompt: str) -> str:
    print(prompt, end="", file=sys.stderr, flush=True)
    return input().strip()


async def main() -> None:
    api_id_raw = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()

    if not api_id_raw or not api_hash:
        print("Missing TELEGRAM_API_ID or TELEGRAM_API_HASH.", file=sys.stderr)
        raise SystemExit(1)

    try:
        api_id = int(api_id_raw)
    except ValueError:
        print("TELEGRAM_API_ID must be a number.", file=sys.stderr)
        raise SystemExit(1)

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    try:
        if not await client.is_user_authorized():
            phone = _stderr_prompt("Phone number: ")
            await client.send_code_request(phone)
            code = _stderr_prompt("Login code: ")
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                password = getpass("Two-step password: ")
                await client.sign_in(password=password)

        me = await client.get_me()
        session_string = StringSession.save(client.session)
        StringSession(session_string)

        username = getattr(me, "username", None) or ""
        print(f"TELEGRAM_SESSION_STRING={session_string}")
        print("Authorized=True")
        print(f"Username={username}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
