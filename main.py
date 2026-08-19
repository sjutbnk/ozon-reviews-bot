from __future__ import annotations
import asyncio
import logging
from telegram.ext import Application
from config import load_settings
from database import Database
from ai_generator import ReplyGenerator
from ozon_client import OzonClient
from poller import ReviewPoller
from handlers.commands import register_commands
from handlers.reviews import register_review_handlers

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

async def run():
    settings = load_settings(); db = Database(settings.database_path)
    app = Application.builder().token(settings.telegram_token.get_secret_value()).build()
    generator = ReplyGenerator(settings.llm_api_key.get_secret_value() if settings.llm_api_key else None, settings.llm_base_url, settings.llm_model, settings.llm_timeout_seconds, settings.max_reply_length)
    ozon = OzonClient(settings.ozon_storage_state, settings.ozon_reviews_url)
    async def deliver(row):
        from handlers.reviews import card
        for uid in db.authorized_users():
            if db.record_delivery(row['review_id'], uid, 0): await app.bot.send_message(uid, *card(row), parse_mode='HTML')
    poller = ReviewPoller(db, ozon, generator, settings.poll_interval_seconds, deliver)
    register_commands(app, db, settings, poller); register_review_handlers(app, db, ozon, generator, settings.max_reply_length)
    try:
        await ozon.start()
    except Exception as exc:
        logging.getLogger(__name__).error('Ozon session is unavailable: %s', exc)
    async with app:
        await app.start(); await app.updater.start_polling()
        poll_task = asyncio.create_task(poller.run())
        try: await asyncio.Event().wait()
        finally:
            poller.stop(); await poll_task; await app.updater.stop(); await app.stop(); await ozon.close()

def main():
    try: asyncio.run(run())
    except KeyboardInterrupt: pass

if __name__ == '__main__': main()
