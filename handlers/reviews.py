from __future__ import annotations

import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)


def card(row) -> tuple[str, InlineKeyboardMarkup]:
    rating = max(0, min(5, int(row["rating"])))
    stars = "★" * rating + "☆" * (5 - rating)
    product_section = ""
    if row.get("product_name"):
        product_section = f"<b>ТОВАР</b>\n{escape(str(row['product_name']))}\n\n"
    review = escape(str(row["text"] or "Текст отзыва отсутствует"))
    draft = escape(str(row["draft"] or "Черновик ещё не сгенерирован."))
    text = (
        "<b>OZON REVIEW DESK</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"<b>РЕЙТИНГ</b>  {stars}  {rating}/5\n\n"
        f"{product_section}"
        f"<b>ОТЗЫВ</b>\n{review}\n\n"
        f"<b>ЧЕРНОВИК ОТВЕТА</b>\n{draft}\n\n"
        "Выберите действие:"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"send:{row['review_id']}"),
            InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{row['review_id']}"),
        ],
        [
            InlineKeyboardButton("🔄 Новый вариант", callback_data=f"regen:{row['review_id']}"),
            InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip:{row['review_id']}"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def _safe_edit(query, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


def register_review_handlers(app, db, ozon, generator, max_length: int) -> None:
    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if not db.is_authorized(q.from_user.id):
            await q.answer("Доступ закрыт.", show_alert=True)
            return
        await q.answer()

        action, rid = q.data.split(":", 1)
        row = db.get_review(rid)
        if not row:
            await _safe_edit(q, "Отзыв не найден.")
            return

        if action == "skip":
            db.skip(rid, q.from_user.id)
            await _safe_edit(q, "Отзыв пропущен.")
            return

        if action == "edit":
            context.user_data["editing"] = rid
            await q.message.reply_text(
                f"Пришлите новый ответ (до {max_length} символов).\nДля отмены введите /cancel"
            )
            return

        if action == "regen":
            try:
                examples = [(r["review"], r["reply"]) for r in db.examples()]
                new_draft = await generator.generate(row["text"], row["rating"], examples)
                db.set_draft(rid, new_draft)
                row = db.get_review(rid)
                body, markup = card(row)
                await _safe_edit(q, body, reply_markup=markup, parse_mode="HTML")
            except Exception as exc:
                await q.message.reply_text(f"Ошибка генерации: {exc}")
            return

        if action == "send":
            if not db.claim_review(rid, q.from_user.id):
                await q.message.reply_text("Отзыв уже обрабатывается или закрыт.")
                return
            await _safe_edit(q, "⏳ <b>Публикуем ответ в Ozon...</b>\nПожалуйста, подождите.", parse_mode="HTML")
            try:
                await ozon.publish_reply(rid, row["draft"])
                db.mark_published(rid, q.from_user.id)
                db.log_action(rid, q.from_user.id, "publish")
                await _safe_edit(q, "✅ <b>Ответ опубликован в Ozon.</b>", parse_mode="HTML")
            except Exception as exc:
                logger.exception("Failed to publish reply to Ozon for %s", rid)
                db.mark_error(rid, str(exc))
                row = db.get_review(rid)
                body, markup = card(row)
                await _safe_edit(
                    q,
                    f"⚠️ <b>Публикация не удалась:</b> {escape(str(exc))}\n\n{body}",
                    reply_markup=markup,
                    parse_mode="HTML",
                )

    async def edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        rid = context.user_data.pop("editing", None)
        if not rid:
            return
        text = update.message.text.strip()
        if not text or len(text) > max_length:
            context.user_data["editing"] = rid
            await update.message.reply_text(f"Ответ должен быть от 1 до {max_length} символов.")
            return
        db.set_draft(rid, text)
        row = db.get_review(rid)
        body, markup = card(row)
        await update.message.reply_text(body, reply_markup=markup, parse_mode="HTML")

    app.add_handler(CallbackQueryHandler(callback, pattern="^(send|edit|regen|skip):"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, edit_text))
