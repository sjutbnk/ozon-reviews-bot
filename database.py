import os
import aiosqlite
from config import DB_PATH


async def init_db():
    dirname = os.path.dirname(DB_PATH)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS authorized_users (
                user_id INTEGER PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS style_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_text TEXT,
                reply_text TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS processed_reviews (
                review_id TEXT PRIMARY KEY,
                replied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()


async def is_authorized(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM authorized_users WHERE user_id = ?", (user_id,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def authorize_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO authorized_users (user_id) VALUES (?)", (user_id,)
        )
        await db.commit()


async def get_style_examples(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT review_text, reply_text FROM style_examples ORDER BY RANDOM() LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def save_style_examples(examples: list[dict]):
    """examples: list of {review_text, reply_text}"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO style_examples (review_text, reply_text) VALUES (:review_text, :reply_text)",
            examples,
        )
        await db.commit()


async def count_style_examples() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM style_examples") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def is_review_processed(review_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM processed_reviews WHERE review_id = ?", (review_id,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_review_processed(review_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO processed_reviews (review_id) VALUES (?)", (review_id,)
        )
        await db.commit()
