import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from database import Database


class DatabaseReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Database(f'{self.directory.name}/bot.sqlite3')
        self.db.upsert_reviews([{'review_id': 'r1', 'rating': 5, 'text': 'ok'}])

    def tearDown(self):
        self.directory.cleanup()

    def test_mark_error_persists_details(self):
        self.db.mark_error('r1', 'Ozon timeout')
        self.assertEqual(self.db.get_review('r1')['last_error'], 'Ozon timeout')

    def test_stale_sending_claim_becomes_retryable_error(self):
        self.assertTrue(self.db.claim_review('r1', 10))
        with self.db.connection() as conn:
            old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            conn.execute("UPDATE reviews SET locked_at=? WHERE review_id='r1'", (old,))

        self.assertEqual(self.db.release_stale_claims(900), 1)
        row = self.db.get_review('r1')
        self.assertEqual(row['status'], 'error')
        self.assertIsNone(row['locked_by'])
