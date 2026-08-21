from __future__ import annotations

import asyncio
import logging

from telegram.error import BadRequest
from telegram.ext import Application, ContextTypes

from ai_generator import ReplyGenerator
from config import load_settings
from database import Database
from handlers.commands import register_commands
from handlers.reviews import card, register_review_handlers
from ozon_client import OzonClient
from poller import ReviewPoller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
        return
    logger.error("Telegram error: %s", context.error, exc_info=context.error)


async def run() -> None:
    settings = load_settings()
    db = Database(settings.database_path)
    app = Application.builder().token(settings.telegram_token.get_secret_value()).build()
    app.add_error_handler(error_handler)

    generator = ReplyGenerator(
        settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_timeout_seconds,
        settings.max_reply_length,
    )
    ozon = OzonClient(settings.ozon_storage_state, settings.ozon_reviews_url)

    async def deliver(row) -> None:
        text, markup = card(row)
        for uid in db.authorized_users():
            if db.is_delivered(row["review_id"], uid):
                continue
            try:
                msg = await app.bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML")
                db.record_delivery(row["review_id"], uid, msg.message_id)
            except Exception as exc:
                logger.warning("Delivery failed for user %s: %s", uid, exc)

    poller = ReviewPoller(db, ozon, generator, settings.poll_interval_seconds, deliver)
    register_commands(app, db, settings, poller, ozon)
    register_review_handlers(app, db, ozon, generator, settings.max_reply_length)

    async with app:
        await app.start()
        await app.updater.start_polling()
        try:
            await ozon.start()
        except Exception as exc:
            logger.error("Ozon session is unavailable: %s", exc)
        poll_task = asyncio.create_task(poller.run())
        try:
            await asyncio.Event().wait()
        finally:
            poller.stop()
            await poll_task
            await app.updater.stop()
            await app.stop()
            await ozon.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
