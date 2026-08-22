import json
import tempfile
import unittest
from pathlib import Path

from ozon_session import SessionFileError, save_storage_state
from ozon_client import OzonClient, SessionExpiredError


class OzonSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.target = Path(self.directory.name) / "ozon_state.json"

    def tearDown(self):
        self.directory.cleanup()

    def test_saves_a_valid_playwright_storage_state(self):
        save_storage_state(b'{"cookies": [], "origins": []}', self.target)

        self.assertEqual(json.loads(self.target.read_text()), {"cookies": [], "origins": []})

    def test_invalid_file_does_not_replace_the_existing_session(self):
        self.target.write_text('{"cookies": [], "origins": []}')

        with self.assertRaises(SessionFileError):
            save_storage_state(b'not json', self.target)

        self.assertEqual(json.loads(self.target.read_text()), {"cookies": [], "origins": []})

    def test_rejects_json_that_is_not_a_playwright_storage_state(self):
        with self.assertRaisesRegex(SessionFileError, "cookies"):
            save_storage_state(b'{"token": "secret"}', self.target)

    def test_limits_size_and_keeps_session_private(self):
        with self.assertRaises(SessionFileError):
            save_storage_state(b'x' * (5 * 1024 * 1024 + 1), self.target)

        save_storage_state(b'{"cookies": [], "origins": []}', self.target)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)

    def test_converts_cookie_editor_array_to_storage_state(self):
        cookie_array = b'[{"name": "__Secure-token", "value": "xyz123", "domain": ".ozon.ru", "path": "/", "expirationDate": 1780000000}]'
        save_storage_state(cookie_array, self.target)
        saved = json.loads(self.target.read_text())
        self.assertIn("cookies", saved)
        self.assertEqual(saved["cookies"][0]["name"], "__Secure-token")
        self.assertEqual(saved["cookies"][0]["value"], "xyz123")
        self.assertEqual(saved["cookies"][0]["domain"], ".ozon.ru")

    def test_converts_cookie_editor_with_utf8_bom_and_null_fields(self):
        cookie_text_with_bom = (
            b'\xef\xbb\xbf[{"name": "__Secure-user-id", "value": "10874408", "domain": ".ozon.ru", '
            b'"path": "/", "sameSite": "lax", "expirationDate": 1818934577.77, "storeId": null}]'
        )
        save_storage_state(cookie_text_with_bom, self.target)
        saved = json.loads(self.target.read_text())
        self.assertEqual(saved["cookies"][0]["name"], "__Secure-user-id")
        self.assertEqual(saved["cookies"][0]["value"], "10874408")
        self.assertEqual(saved["cookies"][0]["sameSite"], "Lax")



class OzonSessionValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_exposes_operation_lock(self):
        self.assertIsNotNone(OzonClient('storage/ozon_state.json', 'https://seller.ozon.ru/app/reviews').operation_lock)

    async def test_validate_session_does_not_require_review_cards(self):
        class Page:
            url = 'https://seller.ozon.ru/app/reviews'

            async def goto(self, url, wait_until):
                self.url = url

        client = OzonClient('storage/ozon_state.json', 'https://seller.ozon.ru/app/reviews')
        client._page = Page()
        await client.validate_session()

    async def test_validate_session_rejects_login_redirect(self):
        class Page:
            url = 'https://seller.ozon.ru/auth'

            async def goto(self, url, wait_until):
                return None

        client = OzonClient('storage/ozon_state.json', 'https://seller.ozon.ru/app/reviews')
        client._page = Page()
        with self.assertRaises(SessionExpiredError):
            await client.validate_session()


if __name__ == "__main__":
    unittest.main()
