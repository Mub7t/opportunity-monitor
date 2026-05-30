import asyncio
import logging
import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession


logging.disable(logging.CRITICAL)
load_dotenv()


async def main() -> None:
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]

    client = TelegramClient("telegram_scraper", api_id, api_hash)
    await client.connect()
    try:
        exported = StringSession.save(client.session)
        StringSession(exported)
        print(f"TELEGRAM_SESSION_STRING={exported}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
