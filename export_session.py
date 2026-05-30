from telethon.sessions import SQLiteSession, StringSession


session = SQLiteSession("telegram_scraper")
print(f"TELEGRAM_SESSION_STRING={StringSession.save(session)}")
