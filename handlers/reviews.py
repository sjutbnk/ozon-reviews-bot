import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ContextTypes
from telegram import Update

from database import is_authorized, mark_review_processed
from ozon_client import post_review_reply
from ai_generator import generate_reply

logger = logging.getLogger(__name__)

# ponytail: in-memory store, restarts lose pending reviews — acceptable for this scale
pending_reviews: dict[str, dict] = {}


def _review_keyboard(review_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Отправить", callback_data=f"send:{review_id}"),
            InlineKeyboardButton("🔄 Перегенерировать", callback_data=f"regen:{review_id}"),
        ],
        [InlineKeyboardButton("❌ Пропустить", callback_data=f"skip:{review_id}")],
    ])


def _format_card(review_text: str, rating: int, reply: str) -> str:
    stars = "⭐" * rating + "☆" * (5 - rating)
    return (
        f"🆕 *Новый отзыв*\n\n"
        f"{stars} \\({rating}/5\\)\n\n"
        f"💬 *Отзыв:*\n{review_text}\n\n"
        f"✏️ *Предложенный ответ:*\n{reply}"
    )


async def send_review_to_manager(bot: Bot, chat_id: int, review: dict):
    review_id = review["review_id"]
    review_text = review.get("text") or "*(текст отсутствует)*"
    rating = review.get("rating", 0)

    generated_reply = await generate_reply(review_text, rating)
    pending_reviews[review_id] = {"text": review_text, "rating": rating, "reply": generated_reply}

    await bot.send_message(
        chat_id=chat_id,
        text=_format_card(review_text, rating, generated_reply),
        parse_mode="MarkdownV2",
        reply_markup=_review_keyboard(review_id),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await is_authorized(query.from_user.id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    action, review_id = query.data.split(":", 1)
    data = pending_reviews.get(review_id)

    if action == "send":
        if not data:
            await query.answer("⚠️ Отзыв не найден в памяти", show_alert=True)
            return
        success = await post_review_reply(review_id, data["reply"])
        if success:
            await mark_review_processed(review_id)
            pending_reviews.pop(review_id, None)
            await query.edit_message_text(
                query.message.text_markdown_v2 + "\n\n✅ *Ответ отправлен на Ozon*",
                parse_mode="MarkdownV2",
            )
        else:
            await query.answer("❌ Ошибка при отправке на Ozon", show_alert=True)

    elif action == "regen":
        if not data:
            await query.answer("⚠️ Отзыв не найден в памяти", show_alert=True)
            return
        await query.answer("⏳ Генерирую новый вариант...")
        new_reply = await generate_reply(data["text"], data["rating"])
        data["reply"] = new_reply
        await query.edit_message_text(
            _format_card(data["text"], data["rating"], new_reply),
            parse_mode="MarkdownV2",
            reply_markup=_review_keyboard(review_id),
        )

    elif action == "skip":
        await mark_review_processed(review_id)
        pending_reviews.pop(review_id, None)
        await query.edit_message_text(
            query.message.text_markdown_v2 + "\n\n❌ *Пропущен*",
            parse_mode="MarkdownV2",
        )
