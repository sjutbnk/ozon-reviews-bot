from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from ai_generator import GenerationError
from ozon_client import OzonError

log = logging.getLogger(__name__)


class ReviewPoller:
    def __init__(
        self,
        db: Any,
        ozon: Any,
        generator: Any,
        interval: int,
        on_review: Callable[[Any], Coroutine[Any, Any, None]],
    ):
        self.db = db
        self.ozon = ozon
        self.generator = generator
        self.interval = interval
        self.on_review = on_review
        self._stop = asyncio.Event()

    async def check_once(self) -> int:
        self.db.release_stale_claims()
        reviews = await self.ozon.fetch_unanswered()
        self.db.upsert_reviews(reviews)

        for old in self.db.pending_reviews():
            if not old["draft"]:
                try:
                    examples = [(r["review"], r["reply"]) for r in self.db.examples()]
                    draft = await self.generator.generate(old["text"], old["rating"], examples)
                    self.db.set_draft(old["review_id"], draft)
                except GenerationError as exc:
                    log.warning("Generation failed for %s: %s", old["review_id"], exc)
                    continue

            review = self.db.get_review(old["review_id"])
            if review:
                await self.on_review(review)

        return len(reviews)

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.check_once()
            except OzonError as exc:
                log.error("Ozon check failed: %s", exc)
            except Exception:
                log.exception("Unexpected poller error")

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

