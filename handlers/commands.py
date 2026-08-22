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
from ozon_session import MAX_STORAGE_STATE_BYTES, OzonLoginWizard, SessionFileError, save_storage_state

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
        "🔐 <b>Подключение Ozon</b>\n\n"
        "<b>Способ 1 (Самый простой для Docker / VPS)</b>:\n"
        "Войдите в <code>seller.ozon.ru</code> в браузере, экспортируйте cookies (через расширение <i>Cookie-Editor</i>) "
        "и просто пришлите JSON-файл или скопированный текст прямо в этот чат.\n\n"
        "<b>Способ 2 (Через окно на компьютере)</b>:\n"
        "Нажмите «Открыть Ozon». Бот откроет окно браузера на этом компьютере. Войдите в Ozon и нажмите «Я вошёл»."
    )


def session_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🌐 Открыть Ozon", callback_data="ozon_session:open")],
            [InlineKeyboardButton("✅ Я вошёл", callback_data="ozon_session:finish")],
            [InlineKeyboardButton("📎 Загрузить файл", callback_data="ozon_session:upload")],
            [InlineKeyboardButton("✖️ Отмена", callback_data="ozon_session:cancel")],
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
            "⚠️ Ozon не подтвердил новую сессию (сессия не авторизована или истекла). "
            "Войдите в Seller и экспортируйте куки заново."
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
            f"Поиск отзывов выполнен. Новых без ответа: <b>{count}</b>.",
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
            await update.message.reply_text("🔒 Неверный пароль. Попробуйте ещё раз.")
            return
        db.authorize(update.effective_user.id)
        await update.message.reply_text(
            f"{APP_TITLE}\n\n✅ Доступ открыт.\nВыберите действие:",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if db.is_authorized(update.effective_user.id):
            await update.message.reply_text(
                f"{APP_TITLE}\n\nВаш рабочий стол для обработки отзывов.\nВыберите действие:",
                reply_markup=main_menu(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"{APP_TITLE}\n\n🔒 Для доступа используйте <code>/auth пароль</code>.",
                parse_mode="HTML",
            )

    async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        try:
            count = await poller.check_once()
            await update.message.reply_text(
                f"🔎 <b>Проверка завершена</b>\nНовых отзывов: <b>{count}</b>", parse_mode="HTML"
            )
        except Exception:
            await update.message.reply_text("⚠️ Не удалось проверить Ozon.\nПроверьте сессию и логи сервера.")

    async def examples(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        await update.message.reply_text(
            "🎨 <b>Стиль ответов</b>\n\nПришлите <code>.csv</code> или <code>.xlsx</code> с колонкой <code>reply</code>.\n"
            "Колонка <code>review</code> необязательна.",
            parse_mode="HTML",
        )
        context.user_data["awaiting_examples"] = True

    async def session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        context.user_data.pop("awaiting_session_upload", None)
        await update.message.reply_text(session_prompt(), reply_markup=session_menu(), parse_mode="HTML")

    async def session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not db.is_authorized(query.from_user.id):
            await query.answer("Доступ закрыт.", show_alert=True)
            return
        await query.answer()

        action = query.data.split(":", 1)[1]
        if action == "open":
            old = context.user_data.pop("ozon_wizard", None)
            if old:
                await old.close()
            wizard = OzonLoginWizard(settings.ozon_reviews_url)
            try:
                await wizard.start()
            except Exception:
                logger.exception("Could not open interactive Ozon login")
                await _safe_edit_text(
                    query,
                    "⚠️ Не удалось открыть окно Ozon на этом компьютере.\n"
                    "Если бот запущен в Docker на VPS, используйте «Загрузить файл».",
                    reply_markup=session_menu(),
                )
                return
            context.user_data["ozon_wizard"] = wizard
            await _safe_edit_text(
                query,
                "🌐 Окно Ozon открыто. Войдите в кабинет, затем нажмите «✅ Я вошёл».",
                reply_markup=session_menu(),
            )
            return

        if action == "upload":
            context.user_data["awaiting_session_upload"] = True
            await _safe_edit_text(
                query,
                "📎 Пришлите JSON-файл сессии Ozon. Бот проверит его и заменит текущую сессию только после проверки.",
                reply_markup=session_menu(),
            )
            return

        if action == "cancel":
            wizard = context.user_data.pop("ozon_wizard", None)
            context.user_data.pop("awaiting_session_upload", None)
            if wizard:
                await wizard.close()
            await _safe_edit_text(query, "Подключение Ozon отменено.")
            return

        if action == "finish":
            wizard = context.user_data.pop("ozon_wizard", None)
            if not wizard:
                await _safe_edit_text(query, "Сначала нажмите «🌐 Открыть Ozon».", reply_markup=session_menu())
                return
            try:
                await wizard.save(settings.ozon_storage_state)
                if ozon is not None:
                    await ozon.restart()
                await _safe_edit_text(query, "✅ Ozon подключён. Бот начнёт проверять отзывы автоматически.")
            except SessionFileError as exc:
                await _safe_edit_text(query, f"⚠️ {exc}", reply_markup=session_menu())
                context.user_data["ozon_wizard"] = wizard
                return
            except Exception:
                logger.exception("Could not finish interactive Ozon login")
                await _safe_edit_text(
                    query, "⚠️ Не удалось сохранить сессию. Попробуйте ещё раз.", reply_markup=session_menu()
                )
            finally:
                if context.user_data.get("ozon_wizard") is not wizard:
                    await wizard.close()

    async def document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not db.is_authorized(update.effective_user.id):
            return
        doc = update.message.document
        file_name = (doc.file_name or "").lower()
        if file_name.endswith(".json") or context.user_data.pop("awaiting_session_upload", False):
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
                "⚠️ Поддерживаются только файлы <code>.csv</code> и <code>.xlsx</code> (или <code>.json</code> для сессии).",
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
                f"✅ <b>Примеры загружены</b>\nДобавлено: <b>{db.add_examples(rows)}</b>", parse_mode="HTML"
            )
        except Exception as exc:
            await update.message.reply_text(f"⚠️ <b>Не удалось загрузить файл</b>\n{exc}", parse_mode="HTML")

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
        if await authorized(db)(update, context):
            n = db.example_count()
            stability = "✅ достаточно для стабильного стиля" if n >= 5 else "🟡 нужно ещё минимум 5 примеров"
            await update.message.reply_text(
                f"📊 <b>Статистика стиля</b>\n\nПримеров: <b>{n}</b>\nСтатус: {stability}", parse_mode="HTML"
            )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        await update.message.reply_text(
            "❓ <b>Помощь</b>\n\n"
            "🔎 Проверить отзывы: запустить поиск новых отзывов.\n"
            "🎨 Стиль ответов: загрузить примеры из CSV/XLSX.\n"
            "🔐 Ozon-сессия: открыть вход Ozon или загрузить готовую сессию.\n"
            "📊 Статистика: посмотреть готовность стиля.\n\n"
            "<code>/auth пароль</code>: открыть доступ.\n"
            "<code>/cancel</code>: отменить текущее действие.",
            parse_mode="HTML",
        )

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(db)(update, context):
            return
        context.user_data.pop("editing", None)
        context.user_data.pop("awaiting_examples", None)
        context.user_data.pop("awaiting_session_upload", None)
        wizard = context.user_data.pop("ozon_wizard", None)
        if wizard:
            await wizard.close()
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
