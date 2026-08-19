import logging
import aiohttp
from config import OZON_CLIENT_ID, OZON_API_KEY, OZON_BASE_URL

logger = logging.getLogger(__name__)

HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json",
}


async def get_unanswered_reviews(page_size: int = 100) -> list[dict]:
    """Fetch reviews without a seller reply from Ozon API."""
    url = f"{OZON_BASE_URL}/v1/review/list"
    payload = {
        "filter": {},
        "page": 1,
        "page_size": page_size,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=HEADERS) as resp:
            raw = await resp.text()
            if resp.status != 200:
                logger.error("Ozon review/list error %s: %s", resp.status, raw)
                resp.raise_for_status()

            data = await resp.json(content_type=None)
            reviews_raw = data.get("reviews", [])

            # Normalize field names: Ozon uses "id", we use "review_id" internally
            result = []
            for r in reviews_raw:
                # Skip reviews that already have a comment/reply from the seller
                if r.get("comments_count", 0) > 0:
                    continue
                result.append({
                    "review_id": str(r.get("id", r.get("review_id", ""))),
                    "text": r.get("text", ""),
                    "rating": r.get("rating", 0),
                    "sku": r.get("sku"),
                    "product_id": r.get("product_id"),
                })

            logger.info("Fetched %d reviews, %d without reply", len(reviews_raw), len(result))
            return result


async def post_review_reply(review_id: str, text: str) -> bool:
    """Send a reply to a specific review. Returns True on success."""
    url = f"{OZON_BASE_URL}/v1/review/comment/create"
    payload = {
        "review_id": review_id,
        "text": text,
        "mark_review_as_processed": True,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=HEADERS) as resp:
            raw = await resp.text()
            if resp.status != 200:
                logger.error("Ozon review/comment/create error %s: %s", resp.status, raw)
            return resp.status == 200
