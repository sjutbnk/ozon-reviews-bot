from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from ozon_client import OzonClient
from ozon_session import MAX_STORAGE_STATE_BYTES, SessionFileError, save_storage_state

logger = logging.getLogger(__name__)

APP_TITLE = "<b>OZON REVIEW DESK</b>"
MAIN_MENU_ACTIONS = (
    ("🔎 Проверить отзывы", "check"),
    ("🎨 Стиль ответов", "examples"),
    ("🔐 Ozon-сессия", "session"),
    ("📊 Статистика", "stats"),
    ("❓ Помощь", "help_cmd"),
)


def authorized(db):
    async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        if not db.is_authorized(update.effective_user.id):
            await update.effective_message.reply_text(
                f"{APP_TITLE}\n\n🔒 Доступ закрыт.\nИспользуйте <code>/auth пароль</code>.",
                parse_mode="HTML",
            )
            return False
        return True

    return check


def session_prompt() -> str:
    return (
        "🔐 <b>Подключение Ozon Seller</b>\n\n"
        "Бот работает на сервере и использует сессию вашего браузера.\n\n"
        "<b>Инструкция по подключению (1 минута):</b>\n\n"
        "1️⃣ <b>Установите Cookie-Editor</b> в браузер на вашем ПК:\n"
        "   • <a href=\"https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm\">Chrome / Яндекс Браузер / Edge / Opera</a>\n"
        "   • <a href=\"https://addons.mozilla.org/ru/firefox/addon/cookie-editor/\">Mozilla Firefox</a>\n\n"
        "2️⃣ <b>Экспортируйте куки</b>:\n"
        "   • Откройте <a href=\"https://seller.ozon.ru/\">seller.ozon.ru</a> и войдите в кабинет продавца.\n"
        "   • Нажмите иконку <b>Cookie-Editor</b> на панели расширений.\n"
        "   • Нажмите <b>Export</b> ➔ <b>Export as JSON</b> (куки скопируются в буфер обмена).\n\n"
        "3️⃣ <b>Отправьте данные боту</b>:\n"
        "   • Просто <b>вставьте скопированный текст</b> сюда в чат (Ctrl+V) или отправьте сохраненный <code>.json</code> / <code>.txt</code> файл.\n\n"
        "<i>Бот автоматически проверит валидность сессии и сразу начнет поиск новых отзывов.</i>"
    )


def session_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 Проверить текущую сессию", callback_data="ozon_session:status")],
            [InlineKeyboardButton("✖️ Закрыть", callback_data="ozon_session:cancel")],
        ]
    )


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [MAIN_MENU_ACTIONS[0][0], MAIN_MENU_ACTIONS[1][0]],
            [MAIN_MENU_ACTIONS[2][0], MAIN_MENU_ACTIONS[3][0]],
            [MAIN_MENU_ACTIONS[4][0]],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


async def _safe_edit_text(query, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def _import_ozon_session(raw: bytes | str, reply_target, db, settings, poller, ozon, user_id: int) -> bool:
    try:
        raw_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
        with tempfile.TemporaryDirectory(dir=Path(settings.ozon_storage_state).parent) as directory:
            candidate = Path(directory) / "ozon_state.json"
            save_storage_state(raw_bytes, candidate)
            probe = OzonClient(candidate, settings.ozon_reviews_url)
            try:
                await probe.start()
                await probe.validate_session()
            finally:
                await probe.close()
    except SessionFileError as exc:
        await reply_target.reply_text(f"⚠️ <b>Сессия не принята:</b>\n{exc}", parse_mode="HTML")
        return False
    except Exception:
        logger.exception("Ozon session upload validation failed")
        await reply_target.reply_text(
            "⚠️ <b>Ozon отклонил сессию</b> (сессия истекла или не завершен вход в Seller).\n"
            "Войдите в <a href=\"https://seller.ozon.ru/\">seller.ozon.ru</a> и экспортируйте куки заново.",
            parse_mode="HTML",
        )
        return False

    try:
        save_storage_state(raw_bytes, settings.ozon_storage_state)
    except Exception:
        logger.exception("Could not save validated Ozon session")
        await reply_target.reply_text("⚠️ Не удалось сохранить проверенный файл сессии.")
        return False

    try:
        if ozon is not None:
            await ozon.restart()
        count = await poller.check_once()
        db.log_action(None, user_id, "upload_ozon_session")
        await reply_target.reply_text(
            f"✅ <b>Ozon-сессия успешно обновлена и проверена!</b>\n"
            f"Поиск отзывов выполнен. Неотвеченных отзывов: <b>{count}</b>.",
            parse_mode="HTML",
        )
        return True
    except Exception:
        logger.exception("Ozon session check failed after upload")
        await reply_target.reply_text(
            "⚠️ Файл сохранён, но при проверке Ozon возникла ошибка. Проверьте логи."
        )
        return True


def register_commands(app, db, settings, poller, ozon=None) -> None:
    async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args or context.args[0] != settings.auth_password.get_secret_value():
            await update.message.reply_text("🔒 Неверный пароль. Попробуйте ещё раз:\n<code>/auth ваш_пароль</code>", parse_mode="HTML")
            return
        db.authorize(update.effective_user.id)
        await update.message.reply_text(
            f"{APP_TITLE}\n\n✅ <b>Доступ открыт.</b>\nВыберите действие в меню ниже:",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if db.is_authorized(update.effective_user.id):
            await update.message.reply_text(
                f"{APP_TITLE}\n\n👋 <b>Рабочий стол обработки отзывов</b>\nВыберите действие в меню ниже:",
                reply_markup=main_menu(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"{APP_TITLE}\n\n🔒 <b>Доступ закрыт.</b>\nДля входа используйте команду:\n<code>/auth пароль</code>",
                parse_mode="HTML",
            )

    async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        try:
            count = await poller.check_once()
            await update.message.reply_text(
                f"🔎 <b>Проверка завершена</b>\nНовых отзывов без ответа: <b>{count}</b>", parse_mode="HTML"
            )
        except Exception:
            await update.message.reply_text("⚠️ Не удалось проверить Ozon.\nПроверьте Ozon-сессию через кнопку «🔐 Ozon-сессия».")

    async def examples(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        await update.message.reply_text(
            "🎨 <b>Стиль ответов</b>\n\n"
            "Пришлите файл <code>.csv</code> или <code>.xlsx</code> с примерами ваших ответов.\n\n"
            "📋 <b>Колонки таблицы:</b>\n"
            "• <code>reply</code> — текст ответа (обязательно)\n"
            "• <code>review</code> — текст отзыва (необязательно)\n\n"
            "<i>Бот сохранит примеры и будет повторять ваш тон и стиль при генерации черновиков.</i>",
            parse_mode="HTML",
        )
        context.user_data["awaiting_examples"] = True

    async def session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        context.user_data.pop("awaiting_session_upload", None)
        await update.message.reply_text(session_prompt(), reply_markup=session_menu(), parse_mode="HTML", disable_web_page_preview=True)

    async def session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not db.is_authorized(query.from_user.id):
            await query.answer("Доступ закрыт.", show_alert=True)
            return
        await query.answer()

        action = query.data.split(":", 1)[1]
        if action == "status":
            if not Path(settings.ozon_storage_state).exists():
                await _safe_edit_text(
                    query,
                    "⚠️ <b>Сессия Ozon ещё не подключена.</b>\n"
                    "Экспортируйте куки из браузера и пришлите их сюда в чат.\n\n" + session_prompt(),
                    reply_markup=session_menu(),
                    parse_mode="HTML",
                )
                return
            await _safe_edit_text(query, "⏳ <b>Проверяем сессию Ozon...</b>", reply_markup=session_menu(), parse_mode="HTML")
            probe = OzonClient(settings.ozon_storage_state, settings.ozon_reviews_url)
            try:
                await probe.start()
                await probe.validate_session()
                await _safe_edit_text(
                    query,
                    "✅ <b>Ozon-сессия активна!</b>\nБот успешно подключён к Ozon Seller и готов к работе.",
                    reply_markup=session_menu(),
                    parse_mode="HTML",
                )
            except Exception:
                await _safe_edit_text(
                    query,
                    "⚠️ <b>Сессия Ozon истекла или недействительна.</b>\n"
                    "Обновите куки в браузере и пришлите новый JSON в чат.\n\n" + session_prompt(),
                    reply_markup=session_menu(),
                    parse_mode="HTML",
                )
            finally:
                await probe.close()
            return

        if action == "cancel":
            context.user_data.pop("awaiting_session_upload", None)
            await _safe_edit_text(query, "Окно настройки сессии закрыто.")
            return

    async def document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not db.is_authorized(update.effective_user.id):
            return
        doc = update.message.document
        file_name = (doc.file_name or "").lower()
        if file_name.endswith((".json", ".txt")) or context.user_data.pop("awaiting_session_upload", False):
            context.user_data.pop("awaiting_session_upload", None)
            if doc.file_size and doc.file_size > MAX_STORAGE_STATE_BYTES:
                await update.message.reply_text("⚠️ Файл сессии слишком большой (максимум 5 МБ).")
                return
            raw = bytes(await (await context.bot.get_file(doc.file_id)).download_as_bytearray())
            await _import_ozon_session(raw, update.message, db, settings, poller, ozon, update.effective_user.id)
            return

        if not context.user_data.pop("awaiting_examples", False):
            if not file_name.endswith((".csv", ".xlsx")):
                return

        if not file_name.endswith((".csv", ".xlsx")):
            await update.message.reply_text(
                "⚠️ Поддерживаются файлы <code>.csv</code> и <code>.xlsx</code> (для примеров) или <code>.json</code> / <code>.txt</code> (для сессии).",
                parse_mode="HTML",
            )
            return
        raw = await (await context.bot.get_file(doc.file_id)).download_as_bytearray()
        try:
            frame = pd.read_csv(io.BytesIO(raw)) if file_name.endswith(".csv") else pd.read_excel(io.BytesIO(raw))
            if "reply" not in frame.columns:
                raise ValueError("отсутствует обязательная колонка reply")
            rows = [
                (str(row.get("review")) if pd.notna(row.get("review")) else None, str(row["reply"]))
                for _, row in frame.iterrows()
                if pd.notna(row["reply"]) and str(row["reply"]).strip()
            ]
            if not rows:
                raise ValueError("нет непустых ответов")
            await update.message.reply_text(
                f"✅ <b>Примеры загружены</b>\nДобавлено в базу: <b>{db.add_examples(rows)}</b>", parse_mode="HTML"
            )
        except Exception as exc:
            await update.message.reply_text(f"⚠️ <b>Не удалось загрузить файл:</b>\n{exc}", parse_mode="HTML")

    async def pasted_json_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not db.is_authorized(update.effective_user.id):
            return
        if context.user_data.get("editing"):
            return
        text = (update.message.text or "").strip()
        if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
            if '"cookies"' in text or '"name"' in text or "ozon.ru" in text or "__Secure" in text:
                await _import_ozon_session(text, update.message, db, settings, poller, ozon, update.effective_user.id)

    async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        n = db.example_count()
        stability = "✅ Достаточно (стиль активен)" if n >= 5 else "🟡 Рекомендуется добавить ещё (минимум 5)"
        has_session = Path(settings.ozon_storage_state).exists()
        session_status = "✅ Подключена" if has_session else "❌ Не подключена"
        text = (
            "📊 <b>Статистика системы</b>\n\n"
            f"📁 <b>Примеров стиля:</b> <code>{n}</code>\n"
            f"🎨 <b>Статус стиля:</b> {stability}\n"
            f"🔐 <b>Ozon-сессия:</b> {session_status}\n\n"
            "<i>Для обновления стиля пришлите .csv или .xlsx с примерами ответов.</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        await update.message.reply_text(
            "❓ <b>Справка по командам</b>\n\n"
            "🔎 <b>Проверить отзывы</b> (<code>/check</code>) — запустить поиск новых отзывов в Ozon\n"
            "🎨 <b>Стиль ответов</b> (<code>/examples</code>) — загрузить таблицу с примерами ответов\n"
            "🔐 <b>Ozon-сессия</b> (<code>/session</code>) — инструкция и проверка сессии Ozon\n"
            "📊 <b>Статистика</b> (<code>/stats</code>) — статус сессии и количество примеров стиля\n"
            "❌ <b>Отмена</b> (<code>/cancel</code>) — отменить текущую загрузку или редактирование",
            parse_mode="HTML",
        )

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        context.user_data.pop("editing", None)
        context.user_data.pop("awaiting_examples", None)
        context.user_data.pop("awaiting_session_upload", None)
        await update.message.reply_text("Действие отменено.", reply_markup=main_menu())

    # 1. Slash commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("examples", examples))
    app.add_handler(CommandHandler("session", session))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel))

    # 2. Main menu reply keyboard buttons
    for label, handler in MAIN_MENU_ACTIONS:
        app.add_handler(MessageHandler(filters.Regex(f"^{label}$"), locals()[handler]))

    # 3. Callback queries
    app.add_handler(CallbackQueryHandler(session_callback, pattern=r"^ozon_session:"))

    # 4. Documents (.json, .csv, .xlsx)
    app.add_handler(MessageHandler(filters.Document.ALL, document))

    # 5. Direct pasted JSON cookies
    app.add_handler(MessageHandler(filters.Regex(r"^\s*[\[\{]") & ~filters.COMMAND, pasted_json_session))
