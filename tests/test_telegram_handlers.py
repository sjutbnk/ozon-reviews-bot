import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from handlers.commands import register_commands


class FakeDb:
    def is_authorized(self, user_id):
        return True


class FakeSettings:
    ozon_reviews_url = 'https://seller.ozon.ru/app/reviews'
    ozon_storage_state = Path(tempfile.gettempdir()) / 'ozon-test-state.json'


class FakeApp:
    def __init__(self):
        self.handlers = {}

    def add_handler(self, handler, group=0):
        self.handlers.setdefault(group, []).append(handler)


class TelegramHandlerIntegrationTests(unittest.TestCase):
    def test_session_command_sends_manager_friendly_instructions(self):
        app = FakeApp()
        register_commands(app, FakeDb(), FakeSettings(), poller=None)
        session_handler = next(
            h for group in app.handlers.values() for h in group
            if getattr(getattr(h, 'callback', None), '__name__', '') == 'session'
        )
        sent = {}

        class Message:
            async def reply_text(self, text, **kwargs):
                sent['text'] = text
                sent['markup'] = kwargs['reply_markup']

        update = SimpleNamespace(effective_user=SimpleNamespace(id=1), message=Message())
        context = SimpleNamespace(user_data={})
        asyncio.run(session_handler.callback(update, context))

        self.assertIn('Cookie-Editor', sent['text'])
        self.assertNotIn('create_ozon_session.py', sent['text'])
        self.assertEqual(sent['markup'].inline_keyboard[0][0].callback_data, 'ozon_session:status')

    def test_cancel_clears_all_user_states(self):
        app = FakeApp()
        register_commands(app, FakeDb(), FakeSettings(), poller=None)
        cancel_handler = next(
            h for group in app.handlers.values() for h in group
            if getattr(getattr(h, 'callback', None), '__name__', '') == 'cancel'
        )
        sent = {}

        class Message:
            async def reply_text(self, text, **kwargs):
                sent['text'] = text

        update = SimpleNamespace(effective_user=SimpleNamespace(id=1), message=Message())
        context = SimpleNamespace(user_data={'editing': 'r1', 'awaiting_examples': True, 'awaiting_session_upload': True})
        asyncio.run(cancel_handler.callback(update, context))

        self.assertEqual(context.user_data, {})
        self.assertIn('Действие отменено', sent['text'])

    def test_error_handler_suppresses_message_not_modified(self):
        from telegram.error import BadRequest
        from main import error_handler

        context = SimpleNamespace(error=BadRequest("Message is not modified: specified new message content"))
        # Should not raise
        asyncio.run(error_handler(None, context))

    def test_all_slash_commands_and_menu_buttons_are_registered(self):
        from telegram.ext import CommandHandler, MessageHandler
        from handlers.commands import MAIN_MENU_ACTIONS

        app = FakeApp()
        register_commands(app, FakeDb(), FakeSettings(), poller=None)

        command_names = {
            cmd for h in app.handlers.get(0, []) if isinstance(h, CommandHandler) for cmd in h.commands
        }
        self.assertTrue({"start", "auth", "check", "examples", "session", "stats", "help", "cancel"}.issubset(command_names))

        button_patterns = [
            h.filters.pattern.pattern for h in app.handlers.get(0, [])
            if isinstance(h, MessageHandler) and getattr(h.filters, "pattern", None) is not None
        ]
        for label, _ in MAIN_MENU_ACTIONS:
            self.assertIn(f"^{label}$", button_patterns)

