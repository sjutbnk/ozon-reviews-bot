from pathlib import Path

class OzonError(RuntimeError): pass
class SessionExpiredError(OzonError): pass
class SelectorChangedError(OzonError): pass

class OzonClient:
    def __init__(self, storage_state, reviews_url):
        self.storage_state, self.reviews_url = Path(storage_state), reviews_url
        self._playwright = self._browser = self._page = None

    async def start(self):
        if not self.storage_state.exists():
            raise SessionExpiredError(f'Файл browser-session не найден: {self.storage_state}')
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        context = await self._browser.new_context(storage_state=str(self.storage_state))
        self._page = await context.new_page()

    async def close(self):
        if self._browser: await self._browser.close()
        if self._playwright: await self._playwright.stop()

    async def fetch_unanswered(self):
        if not self._page: raise OzonError('Ozon client не запущен')
        await self._page.goto(self.reviews_url, wait_until='domcontentloaded')
        if 'login' in self._page.url.lower() or 'auth' in self._page.url.lower():
            raise SessionExpiredError('Сессия Ozon истекла. Пересоздайте browser-session.')
        try: await self._page.wait_for_selector('[data-review-id]', timeout=10000)
        except Exception as exc: raise SelectorChangedError('Ozon: не найден локатор отзывов; интерфейс мог измениться') from exc
        result = []
        for item in await self._page.locator('[data-review-id]').all():
            if await item.locator("[data-answered='true']").count(): continue
            result.append({'review_id': await item.get_attribute('data-review-id'), 'rating': int(await item.get_attribute('data-rating') or 0), 'text': (await item.inner_text()).strip(), 'product_name': await item.get_attribute('data-product-name')})
        return [r for r in result if r['review_id']]

    async def publish_reply(self, review_id, text):
        if not self._page: raise OzonError('Ozon client не запущен')
        card = self._page.locator(f"[data-review-id='{review_id}']")
        if await card.count() == 0: raise SelectorChangedError('Ozon: карточка отзыва не найдена')
        try:
            await card.locator('textarea').fill(text)
            await card.locator("button[data-action='reply']").click()
            await card.locator("[data-answered='true']").wait_for(timeout=10000)
        except Exception as exc: raise OzonError('Не удалось опубликовать ответ в Ozon') from exc

