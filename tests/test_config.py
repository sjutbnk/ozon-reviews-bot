import unittest

from config import Settings


class ConfigTests(unittest.TestCase):
    def test_default_reviews_url_uses_ozon_seller(self):
        settings = Settings(
            TELEGRAM_TOKEN="test-token",
            AUTH_PASSWORD="test-password",
            _env_file=None,
        )

        self.assertEqual(settings.ozon_reviews_url, "https://seller.ozon.ru/app/reviews")


if __name__ == "__main__":
    unittest.main()
