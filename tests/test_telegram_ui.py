import unittest

from handlers.commands import main_menu
from handlers.commands import register_commands
from handlers.reviews import card
from handlers.commands import session_menu, session_prompt
from telegram.ext import Application


class TelegramUiTests(unittest.TestCase):
    def test_register_commands_registers_every_menu_action(self):
        app = Application.builder().token("123456:ABC").build()

        register_commands(app, db=None, settings=None, poller=None)
        callbacks = [handler for group in app.handlers.values() for handler in group if handler.__class__.__name__ == 'CallbackQueryHandler']
        documents = [handler for group in app.handlers.values() for handler in group if handler.__class__.__name__ == 'MessageHandler']
        self.assertTrue(any(getattr(handler, 'pattern', None) and handler.pattern.pattern == r'^ozon_session:' for handler in callbacks))
        self.assertTrue(any(getattr(handler, 'filters', None) is not None for handler in documents))

    def test_main_menu_exposes_all_manager_actions(self):
        labels = [button.text for row in main_menu().keyboard for button in row]

        self.assertEqual(
            labels,
            [
                "🔎 Проверить отзывы",
                "🎨 Стиль ответов",
                "🔐 Ozon-сессия",
                "📊 Статистика",
                "❓ Помощь",
            ],
        )

    def test_review_card_has_clear_sections_and_escapes_review(self):
        text, markup = card(
            {
                "review_id": "review-1",
                "rating": 4,
                "text": "Товар <b>хороший</b>",
                "draft": "Спасибо & ждём вас снова!",
            }
        )

        self.assertIn("<b>OZON REVIEW DESK</b>", text)
        self.assertIn("<b>ОТЗЫВ</b>", text)
        self.assertIn("Товар &lt;b&gt;хороший&lt;/b&gt;", text)
        self.assertIn("Спасибо &amp; ждём вас снова!", text)
        self.assertEqual(
            [button.text for row in markup.inline_keyboard for button in row],
            ["✅ Опубликовать", "✏️ Изменить", "🔄 Новый вариант", "⏭ Пропустить"],
        )

    def test_review_card_renders_product_name_when_present(self):
        text, _ = card(
            {
                "review_id": "review-2",
                "rating": 5,
                "text": "Отличный товар",
                "draft": "Спасибо!",
                "product_name": "Беспроводные наушники Pro",
            }
        )
        self.assertIn("<b>ТОВАР</b>\nБеспроводные наушники Pro", text)

    def test_session_flow_is_clear_and_offers_browser_setup(self):
        self.assertNotIn("create_ozon_session.py", session_prompt())
        labels = [button.text for row in session_menu().inline_keyboard for button in row]
        self.assertEqual(labels, ["🌐 Открыть Ozon", "✅ Я вошёл", "📎 Загрузить файл", "✖️ Отмена"])


if __name__ == "__main__":
    unittest.main()
