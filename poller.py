import asyncio
import logging
from ai_generator import GenerationError
from ozon_client import OzonError

log = logging.getLogger(__name__)
class ReviewPoller:
    def __init__(self, db, ozon, generator, interval, on_review): self.db, self.ozon, self.generator, self.interval, self.on_review = db, ozon, generator, interval, on_review; self._stop = asyncio.Event()
    async def check_once(self):
        reviews = await self.ozon.fetch_unanswered(); self.db.upsert_reviews(reviews)
        for old in self.db.pending_reviews():
            if not old['draft']:
                try: self.db.set_draft(old['review_id'], await self.generator.generate(old['text'], old['rating'], [(r['review'], r['reply']) for r in self.db.examples()]))
                except GenerationError as exc: log.warning('generation failed for %s: %s', old['review_id'], exc); continue
            await self.on_review(self.db.get_review(old['review_id']))
        return len(reviews)
    async def run(self):
        while not self._stop.is_set():
            try: await self.check_once()
            except OzonError as exc: log.error('Ozon check failed: %s', exc)
            except Exception: log.exception('Unexpected poller error')
            try: await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError: pass
    def stop(self): self._stop.set()

