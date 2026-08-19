from __future__ import annotations
import io
import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes

APP_TITLE = '<b>OZON REVIEW DESK</b>'
MAIN_MENU_ACTIONS = (
    ('🔎 Проверить отзывы', 'check'),
    ('🎨 Стиль ответов', 'examples'),
    ('📊 Статистика', 'stats'),
    ('❓ Помощь', 'help'),
)


def authorized(db):
    async def check(update, context):
        if not db.is_authorized(update.effective_user.id):
            await update.effective_message.reply_text(
                f'{APP_TITLE}\n\n🔒 Доступ закрыт.\nИспользуйте <code>/auth пароль</code>.',
                parse_mode='HTML',
            )
            return False
        return True
    return check


def register_commands(app, db, settings, poller):
    async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or context.args[0] != settings.auth_password.get_secret_value():
            await update.message.reply_text('🔒 Неверный пароль. Попробуйте ещё раз.')
            return
        db.authorize(update.effective_user.id)
        await update.message.reply_text(
            f'{APP_TITLE}\n\n✅ Доступ открыт.\nВыберите действие:',
            reply_markup=main_menu(),
            parse_mode='HTML',
        )

    async def start(update, context):
        if db.is_authorized(update.effective_user.id):
            await update.message.reply_text(
                f'{APP_TITLE}\n\nВаш рабочий стол для обработки отзывов.\nВыберите действие:',
                reply_markup=main_menu(),
                parse_mode='HTML',
            )
        else:
            await update.message.reply_text(
                f'{APP_TITLE}\n\n🔒 Для доступа используйте <code>/auth пароль</code>.',
                parse_mode='HTML',
            )

    async def check(update, context):
        if not await authorized(db)(update, context): return
        try:
            count = await poller.check_once()
            await update.message.reply_text(f'🔎 <b>Проверка завершена</b>\nНовых отзывов: <b>{count}</b>', parse_mode='HTML')
        except Exception:
            await update.message.reply_text('⚠️ Не удалось проверить Ozon.\nПроверьте сессию и логи сервера.')

    async def examples(update, context):
        if not await authorized(db)(update, context): return
        await update.message.reply_text(
            '🎨 <b>Стиль ответов</b>\n\nПришлите <code>.csv</code> или <code>.xlsx</code> с колонкой <code>reply</code>.\n'
            'Колонка <code>review</code> необязательна.',
            parse_mode='HTML',
        )
        context.user_data['awaiting_examples'] = True

    async def document(update, context):
        if not db.is_authorized(update.effective_user.id) or not context.user_data.pop('awaiting_examples', False): return
        doc = update.message.document
        if not doc.file_name.lower().endswith(('.csv', '.xlsx')):
            await update.message.reply_text('⚠️ Поддерживаются только файлы <code>.csv</code> и <code>.xlsx</code>.', parse_mode='HTML')
            return
        raw = await (await context.bot.get_file(doc.file_id)).download_as_bytearray()
        try:
            frame = pd.read_csv(io.BytesIO(raw)) if doc.file_name.lower().endswith('.csv') else pd.read_excel(io.BytesIO(raw))
            if 'reply' not in frame.columns: raise ValueError('отсутствует обязательная колонка reply')
            rows = [(str(row.get('review')) if pd.notna(row.get('review')) else None, str(row['reply'])) for _, row in frame.iterrows() if pd.notna(row['reply']) and str(row['reply']).strip()]
            if not rows: raise ValueError('нет непустых ответов')
            await update.message.reply_text(f'✅ <b>Примеры загружены</b>\nДобавлено: <b>{db.add_examples(rows)}</b>', parse_mode='HTML')
        except Exception as exc:
            await update.message.reply_text(f'⚠️ <b>Не удалось загрузить файл</b>\n{exc}', parse_mode='HTML')

    async def stats(update, context):
        if await authorized(db)(update, context):
            n = db.example_count()
            stability = '✅ достаточно для стабильного стиля' if n >= 5 else '🟡 нужно ещё минимум 5 примеров'
            await update.message.reply_text(f'📊 <b>Статистика стиля</b>\n\nПримеров: <b>{n}</b>\nСтатус: {stability}', parse_mode='HTML')

    async def help_cmd(update, context):
        if not await authorized(db)(update, context): return
        await update.message.reply_text(
            '❓ <b>Помощь</b>\n\n'
            '🔎 Проверить отзывы: запустить поиск новых отзывов.\n'
            '🎨 Стиль ответов: загрузить примеры из CSV/XLSX.\n'
            '📊 Статистика: посмотреть готовность стиля.\n\n'
            '<code>/auth пароль</code>: открыть доступ.',
            parse_mode='HTML',
        )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('auth', auth))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, document))
    for label, handler in MAIN_MENU_ACTIONS:
        app.add_handler(MessageHandler(filters.Regex(f'^{label}$'), locals()[handler]))

def main_menu():
    from telegram import ReplyKeyboardMarkup
    return ReplyKeyboardMarkup(
        [
            [MAIN_MENU_ACTIONS[0][0], MAIN_MENU_ACTIONS[1][0]],
            [MAIN_MENU_ACTIONS[2][0], MAIN_MENU_ACTIONS[3][0]],
        ],
        resize_keyboard=True,
        input_field_placeholder='Выберите действие',
    )

from telegram.ext import CommandHandler, MessageHandler, filters
