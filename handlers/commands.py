import io
import logging
import pandas as pd

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from config import BOT_PASSWORD
from database import (
    authorize_user,
    is_authorized,
    save_style_examples,
    count_style_examples,
    is_review_processed,
)
from ozon_client import get_unanswered_reviews
from handlers.reviews import send_review_to_manager
import poller

logger = logging.getLogger(__name__)

# ─── Keyboard ─────────────────────────────────────────────────────────────────

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🔍 Проверить отзывы"), KeyboardButton("📎 Загрузить примеры")],
        [KeyboardButton("📊 Статистика"),        KeyboardButton("❓ Помощь")],
    ],
    resize_keyboard=True,
    persistent=True,
)


def main_keyboard():
    return MAIN_KEYBOARD


# ─── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_authorized(user_id):
        poller.add_subscriber(user_id)
        await update.message.reply_text(
            "👋 Добро пожаловать!\n\n"
            "Бот автоматически проверяет новые отзывы на Ozon каждые 5 минут "
            "и предлагает готовые ответы в вашем стиле.",
            reply_markup=main_keyboard(),
        )
    else:
        await update.message.reply_text(
            "👋 Привет! Для доступа к боту введите:\n/auth <пароль>",
        )


# ─── /auth ────────────────────────────────────────────────────────────────────

async def cmd_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("❌ Укажите пароль: /auth <пароль>")
        return

    if args[0] == BOT_PASSWORD:
        await authorize_user(user_id)
        poller.add_subscriber(user_id)
        await update.message.reply_text(
            "✅ Доступ открыт!\n\n"
            "Теперь вы будете получать уведомления о новых отзывах.\n"
            "Используйте кнопки ниже для управления ботом.",
            reply_markup=main_keyboard(),
        )
    else:
        await update.message.reply_text("❌ Неверный пароль.")


# ─── Кнопка «❓ Помощь» ────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "📖 *Возможности бота:*\n\n"
        "🔍 *Проверить отзывы* — вручную проверить новые отзывы на Ozon прямо сейчас\n"
        "📎 *Загрузить примеры* — загрузить Excel/CSV с примерами ответов для обучения стилю\n"
        "📊 *Статистика* — сколько примеров ответов загружено в базу\n\n"
        "*Формат файла с примерами:*\n"
        "Два столбца: `review` и `reply`\n"
        "Столбец `review` необязателен — можно только `reply`\n\n"
        "Бот автоматически проверяет отзывы каждые 5 минут.",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ─── Кнопка «📊 Статистика» ───────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update.effective_user.id):
        return
    count = await count_style_examples()
    await update.message.reply_text(
        f"📊 Примеров ответов в базе: *{count}*\n\n"
        f"{'✅ Бот обучен вашему стилю.' if count >= 5 else '⚠️ Рекомендуется загрузить минимум 5 примеров для точной стилизации.'}",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ─── Кнопка «🔍 Проверить отзывы» ────────────────────────────────────────────

async def cmd_check_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update.effective_user.id):
        return

    status_msg = await update.message.reply_text("🔍 Проверяю новые отзывы на Ozon...")
    try:
        reviews = await get_unanswered_reviews()
        new = [r for r in reviews if not await is_review_processed(r["review_id"])]

        if not new:
            await status_msg.edit_text("✅ Новых отзывов без ответа нет.")
            return

        await status_msg.edit_text(
            f"📨 Найдено новых отзывов: *{len(new)}*. Генерирую ответы...",
            parse_mode="Markdown",
        )
        for review in new:
            await send_review_to_manager(context.bot, update.effective_chat.id, review)

    except Exception as e:
        logger.exception("Error in check_reviews")
        await status_msg.edit_text(f"❌ Ошибка при получении отзывов:\n{e}")


# ─── Кнопка «📎 Загрузить примеры» ───────────────────────────────────────────

async def cmd_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "📎 Отправьте файл Excel (.xlsx) или CSV (.csv) с двумя столбцами:\n\n"
        "• `review` — текст отзыва *(необязательно)*\n"
        "• `reply` — текст вашего ответа *(обязательно)*",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ─── Обработчик кнопок клавиатуры ────────────────────────────────────────────

BUTTON_HANDLERS = {
    "🔍 Проверить отзывы": cmd_check_reviews,
    "📎 Загрузить примеры": cmd_upload,
    "📊 Статистика":        cmd_stats,
    "❓ Помощь":            cmd_help,
}


async def handle_keyboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    handler = BUTTON_HANDLERS.get(text)
    if handler:
        await handler(update, context)


# ─── Обработчик документов ────────────────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update.effective_user.id):
        return

    doc = update.message.document
    if not doc.file_name.endswith((".xlsx", ".csv")):
        await update.message.reply_text("❌ Поддерживаются только .xlsx и .csv файлы.")
        return

    tg_file = await doc.get_file()
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    buf.seek(0)

    try:
        df = pd.read_csv(buf) if doc.file_name.endswith(".csv") else pd.read_excel(buf)
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось прочитать файл: {e}")
        return

    df.columns = [c.strip().lower() for c in df.columns]

    if "reply" not in df.columns:
        await update.message.reply_text(
            "❌ В файле нет столбца `reply` с текстами ответов.",
            parse_mode="Markdown",
        )
        return

    df = df.dropna(subset=["reply"])
    examples = [
        {
            "review_text": str(row.get("review", "")) if "review" in df.columns else "",
            "reply_text": str(row["reply"]),
        }
        for _, row in df.iterrows()
    ]

    await save_style_examples(examples)
    await update.message.reply_text(
        f"✅ Загружено *{len(examples)}* примеров ответов.\n\n"
        f"Бот теперь будет использовать ваш стиль при генерации ответов.",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )
