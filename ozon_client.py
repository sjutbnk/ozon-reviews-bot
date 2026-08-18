import aiohttp
from config import OZON_CLIENT_ID, OZON_API_KEY, OZON_BASE_URL

HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json",
}


async def get_unanswered_reviews(page_size: int = 100) -> list[dict]:
    """Fetch reviews without a seller reply."""
    url = f"{OZON_BASE_URL}/v1/review/list"
    payload = {
        "with_response": False,
        "page_size": page_size,
        "sort_dir": "DESC",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=HEADERS) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("reviews", [])


async def post_review_reply(review_id: str, text: str) -> bool:
    """Send a reply to a specific review. Returns True on success."""
    url = f"{OZON_BASE_URL}/v1/review/comment/create"
    payload = {"review_id": review_id, "text": text}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=HEADERS) as resp:
            return resp.status == 200
