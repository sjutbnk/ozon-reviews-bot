from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS authorized_users (
                user_id INTEGER PRIMARY KEY, authorized_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS style_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT, review TEXT, reply TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY, rating INTEGER NOT NULL, text TEXT NOT NULL,
                product_name TEXT, status TEXT NOT NULL DEFAULT 'new', draft TEXT,
                locked_by INTEGER, locked_at TEXT, published_at TEXT, last_error TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                review_id TEXT NOT NULL, user_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                delivered_at TEXT NOT NULL, PRIMARY KEY(review_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT, user_id INTEGER,
                action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);
            """)
            columns = {row[1] for row in c.execute("PRAGMA table_info(reviews)")}
            if 'last_error' not in columns:
                c.execute('ALTER TABLE reviews ADD COLUMN last_error TEXT')

    def is_authorized(self, user_id: int) -> bool:
        with self.connection() as c:
            return c.execute("SELECT 1 FROM authorized_users WHERE user_id=?", (user_id,)).fetchone() is not None

    def authorized_users(self) -> list[int]:
        with self.connection() as c:
            return [int(row[0]) for row in c.execute("SELECT user_id FROM authorized_users").fetchall()]

    def authorize(self, user_id: int) -> None:
        with self.connection() as c:
            c.execute("INSERT OR IGNORE INTO authorized_users VALUES (?, ?)", (user_id, utcnow()))

    def add_examples(self, rows: list[tuple[str | None, str]]) -> int:
        clean = [(review, reply.strip(), utcnow()) for review, reply in rows if reply and reply.strip()]
        with self.connection() as c:
            c.executemany("INSERT INTO style_examples(review, reply, created_at) VALUES (?, ?, ?)", clean)
        return len(clean)

    def example_count(self) -> int:
        with self.connection() as c:
            return int(c.execute("SELECT COUNT(*) FROM style_examples").fetchone()[0])

    def examples(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connection() as c:
            return c.execute("SELECT review, reply FROM style_examples ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def upsert_reviews(self, reviews: list[dict]) -> int:
        with self.connection() as c:
            for r in reviews:
                c.execute("""INSERT INTO reviews(review_id,rating,text,product_name,updated_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(review_id) DO UPDATE SET rating=excluded.rating,
                    text=excluded.text, product_name=excluded.product_name, updated_at=excluded.updated_at
                    WHERE reviews.status IN ('new','error')""",
                    (str(r["review_id"]), int(r.get("rating", 0)), r.get("text", ""), r.get("product_name"), utcnow()))
        return len(reviews)

    def pending_reviews(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connection() as c:
            return c.execute("SELECT * FROM reviews WHERE status IN ('new','error') ORDER BY updated_at LIMIT ?", (limit,)).fetchall()

    def set_draft(self, review_id: str, draft: str) -> None:
        with self.connection() as c:
            c.execute("UPDATE reviews SET draft=?, status='ready', updated_at=? WHERE review_id=? AND status IN ('new','error','ready')", (draft, utcnow(), review_id))

    def get_review(self, review_id: str) -> sqlite3.Row | None:
        with self.connection() as c:
            return c.execute("SELECT * FROM reviews WHERE review_id=?", (review_id,)).fetchone()

    def claim_review(self, review_id: str, user_id: int) -> bool:
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT status,locked_by FROM reviews WHERE review_id=?", (review_id,)).fetchone()
            if not row or row[0] in ("published", "skipped", "sending"):
                c.rollback(); return False
            c.execute("UPDATE reviews SET status='sending',locked_by=?,locked_at=?,last_error=NULL,updated_at=? WHERE review_id=?", (user_id, utcnow(), utcnow(), review_id))
            c.commit(); return True

    def mark_published(self, review_id: str, user_id: int) -> None:
        with self.connection() as c:
            c.execute("UPDATE reviews SET status='published',published_at=?,locked_by=NULL,locked_at=NULL,last_error=NULL,updated_at=? WHERE review_id=? AND status='sending' AND locked_by=?", (utcnow(), utcnow(), review_id, user_id))

    def mark_error(self, review_id: str, details: str = "") -> None:
        with self.connection() as c:
            c.execute("UPDATE reviews SET status='error',locked_by=NULL,locked_at=NULL,last_error=?,updated_at=? WHERE review_id=?", (details[:2000], utcnow(), review_id))

    def release_stale_claims(self, max_age_seconds: int = 900) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)).isoformat()
        with self.connection() as c:
            cur = c.execute(
                """UPDATE reviews SET status='error', locked_by=NULL, locked_at=NULL,
                   last_error='Отправка прервана после тайм-аута', updated_at=?
                   WHERE status='sending' AND locked_at IS NOT NULL AND locked_at < ?""",
                (utcnow(), cutoff),
            )
            return cur.rowcount

    def skip(self, review_id: str, user_id: int) -> None:
        with self.connection() as c:
            c.execute("UPDATE reviews SET status='skipped',locked_by=NULL,updated_at=? WHERE review_id=? AND status NOT IN ('published','skipped')", (utcnow(), review_id))
        self.log_action(review_id, user_id, "skip")

    def is_delivered(self, review_id: str, user_id: int) -> bool:
        with self.connection() as c:
            return c.execute("SELECT 1 FROM deliveries WHERE review_id=? AND user_id=?", (review_id, user_id)).fetchone() is not None

    def record_delivery(self, review_id: str, user_id: int, message_id: int) -> bool:
        with self.connection() as c:
            cur = c.execute("INSERT OR REPLACE INTO deliveries VALUES (?, ?, ?, ?)", (review_id, user_id, message_id, utcnow()))
            return cur.rowcount == 1

    def log_action(self, review_id: str, user_id: int, action: str, details: str = "") -> None:
        with self.connection() as c:
            c.execute("INSERT INTO actions(review_id,user_id,action,details,created_at) VALUES(?,?,?,?,?)", (review_id, user_id, action, details, utcnow()))
