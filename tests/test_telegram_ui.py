import unittest

from handlers.commands import main_menu
from handlers.reviews import card


class TelegramUiTests(unittest.TestCase):
    def test_main_menu_exposes_all_manager_actions(self):
        labels = [button.text for row in main_menu().keyboard for button in row]

        self.assertEqual(
            labels,
            [
                "🔎 Проверить отзывы",
                "🎨 Стиль ответов",
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


if __name__ == "__main__":
    unittest.main()
