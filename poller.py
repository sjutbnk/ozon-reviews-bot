"""Background polling task for Ozon reviews."""
import asyncio
import logging

from telegram import Bot

from config import POLL_INTERVAL_SECONDS
from database import is_review_processed
from ozon_client import get_unanswered_reviews
from handlers.reviews import send_review_to_manager

logger = logging.getLogger(__name__)

_subscribers: set[int] = set()


def add_subscriber(user_id: int):
    _subscribers.add(user_id)


def remove_subscriber(user_id: int):
    _subscribers.discard(user_id)


async def poll_reviews(bot: Bot):
    logger.info("Poller started (interval=%ds)", POLL_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        if not _subscribers:
            continue
        try:
            reviews = await get_unanswered_reviews()
            new = [r for r in reviews if not await is_review_processed(r["review_id"])]
            logger.info("%d unanswered, %d new", len(reviews), len(new))
            for review in new:
                for chat_id in list(_subscribers):
                    await send_review_to_manager(bot, chat_id, review)
        except Exception:
            logger.exception("Poller error")
