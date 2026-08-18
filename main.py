"""Entry point."""
import asyncio
import logging

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from database import init_db
from handlers.commands import (
    cmd_start,
    cmd_auth,
    cmd_help,
    cmd_stats,
    cmd_check_reviews,
    cmd_upload,
    handle_document,
    handle_keyboard_button,
    BUTTON_HANDLERS,
)
from handlers.reviews import handle_callback
from poller import poll_reviews

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def post_init(app: Application):
    await init_db()
    asyncio.create_task(poll_reviews(app.bot))


def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands (slash)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("auth", cmd_auth))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("check_reviews", cmd_check_reviews))
    app.add_handler(CommandHandler("upload", cmd_upload))

    # Keyboard buttons (text messages matching button labels)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex("^(" + "|".join(BUTTON_HANDLERS.keys()) + ")$"),
        handle_keyboard_button,
    ))

    # Documents & Inline callbacks
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
