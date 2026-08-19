from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, filters

EDITING = 1
def card(row):
    text = f'⭐ {row["rating"]}/5\n{row["text"]}\n\n<b>Черновик:</b>\n{row["draft"] or "нет"}'
    keyboard = [[InlineKeyboardButton('Отправить', callback_data=f'send:{row["review_id"]}'), InlineKeyboardButton('Изменить', callback_data=f'edit:{row["review_id"]}')], [InlineKeyboardButton('Перегенерировать', callback_data=f'regen:{row["review_id"]}'), InlineKeyboardButton('Пропустить', callback_data=f'skip:{row["review_id"]}')]]
    return text, InlineKeyboardMarkup(keyboard)

def register_review_handlers(app, db, ozon, generator, max_length):
    async def deliver(row, bot):
        for uid in db.authorized_users() if hasattr(db, 'authorized_users') else []:
            if db.record_delivery(row['review_id'], uid, 0): await bot.send_message(uid, *card(row), parse_mode='HTML')
    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query; await q.answer(); uid = q.from_user.id
        if not db.is_authorized(uid): return
        action, rid = q.data.split(':', 1); row = db.get_review(rid)
        if not row: await q.edit_message_text('Отзыв не найден.'); return
        if action == 'skip': db.skip(rid, uid); await q.edit_message_text('Отзыв пропущен.'); return
        if action == 'edit': context.user_data['editing'] = rid; await q.message.reply_text(f'Пришлите новый ответ (до {max_length} символов). /cancel — отмена'); return
        if action == 'regen':
            try:
                db.set_draft(rid, await generator.generate(row['text'], row['rating'], [(r['review'], r['reply']) for r in db.examples()])); row = db.get_review(rid)
                body, markup = card(row); await q.edit_message_text(body, reply_markup=markup, parse_mode='HTML')
            except Exception as exc: await q.message.reply_text(f'Ошибка генерации: {exc}')
        if action == 'send':
            if not db.claim_review(rid, uid): await q.message.reply_text('Отзыв уже обрабатывается или закрыт.'); return
            try: await ozon.publish_reply(rid, row['draft']); db.mark_published(rid, uid); db.log_action(rid, uid, 'publish'); await q.edit_message_text('Ответ опубликован.')
            except Exception as exc: db.mark_error(rid, str(exc)); await q.message.reply_text(f'Публикация не удалась: {exc}')
    async def edit_text(update, context):
        rid = context.user_data.pop('editing', None)
        if not rid: return
        text = update.message.text.strip()
        if not text or len(text) > max_length: await update.message.reply_text(f'Ответ должен быть от 1 до {max_length} символов.'); context.user_data['editing'] = rid; return
        db.set_draft(rid, text); row = db.get_review(rid); body, markup = card(row); await update.message.reply_text(body, reply_markup=markup, parse_mode='HTML')
    app.add_handler(CallbackQueryHandler(callback, pattern='^(send|edit|regen|skip):'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, edit_text))
