from __future__ import annotations
import io
import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes

def authorized(db):
    async def check(update, context):
        if not db.is_authorized(update.effective_user.id):
            await update.effective_message.reply_text('Доступ закрыт. Используйте /auth <пароль>.')
            return False
        return True
    return check

def register_commands(app, db, settings, poller):
    async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or context.args[0] != settings.auth_password.get_secret_value():
            await update.message.reply_text('Неверный пароль.')
            return
        db.authorize(update.effective_user.id)
        await update.message.reply_text('Доступ открыт.', reply_markup=main_menu())

    async def start(update, context):
        if db.is_authorized(update.effective_user.id): await update.message.reply_text('Главное меню', reply_markup=main_menu())
        else: await update.message.reply_text('Для доступа выполните /auth <пароль>.')

    async def check(update, context):
        if not await authorized(db)(update, context): return
        try: count = await poller.check_once(); await update.message.reply_text(f'Проверка завершена. Найдено отзывов: {count}.')
        except Exception as exc: await update.message.reply_text(f'Ошибка проверки Ozon: {exc}')

    async def examples(update, context):
        if not await authorized(db)(update, context): return
        await update.message.reply_text('Пришлите файл .csv или .xlsx с колонкой reply (review необязательна).')
        context.user_data['awaiting_examples'] = True

    async def document(update, context):
        if not db.is_authorized(update.effective_user.id) or not context.user_data.pop('awaiting_examples', False): return
        doc = update.message.document
        if not doc.file_name.lower().endswith(('.csv', '.xlsx')): await update.message.reply_text('Поддерживаются только .csv и .xlsx.'); return
        raw = await (await context.bot.get_file(doc.file_id)).download_as_bytearray()
        try:
            frame = pd.read_csv(io.BytesIO(raw)) if doc.file_name.lower().endswith('.csv') else pd.read_excel(io.BytesIO(raw))
            if 'reply' not in frame.columns: raise ValueError('отсутствует обязательная колонка reply')
            rows = [(str(row.get('review')) if pd.notna(row.get('review')) else None, str(row['reply'])) for _, row in frame.iterrows() if pd.notna(row['reply']) and str(row['reply']).strip()]
            if not rows: raise ValueError('нет непустых ответов')
            await update.message.reply_text(f'Загружено примеров: {db.add_examples(rows)}.')
        except Exception as exc: await update.message.reply_text(f'Неверный файл: {exc}')

    async def stats(update, context):
        if await authorized(db)(update, context):
            n = db.example_count(); await update.message.reply_text(f'Примеров стиля: {n}. Стиль стабилен: {"да" if n >= 5 else "нет (нужно минимум 5)"}.')
    async def help_cmd(update, context): await update.message.reply_text('/auth <пароль> — вход\nПроверить отзывы — запуск проверки\nЗагрузить примеры — CSV/XLSX\nСтатистика — состояние стиля')
    app.add_handler(CommandHandler('start', start)); app.add_handler(CommandHandler('auth', auth)); app.add_handler(CommandHandler('help', help_cmd)); app.add_handler(MessageHandler(filters.Document.ALL, document));
    for label, fn in [('Проверить отзывы', check), ('Загрузить примеры', examples), ('Статистика', stats)]: app.add_handler(MessageHandler(filters.Regex(f'^{label}$'), fn))

def main_menu():
    from telegram import ReplyKeyboardMarkup
    return ReplyKeyboardMarkup([['Проверить отзывы'], ['Загрузить примеры', 'Статистика'], ['Помощь']], resize_keyboard=True)

from telegram.ext import CommandHandler, MessageHandler, filters

