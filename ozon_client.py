import asyncio
import re
from pathlib import Path


class OzonError(RuntimeError):
    pass


class SessionExpiredError(OzonError):
    pass


class SelectorChangedError(OzonError):
    pass


REVIEW_CARD_SELECTORS = (
    '[data-review-id]',
    '[data-testid="review-card"]',
    '[data-test-id="review-card"]',
    'article',
)
REPLY_INPUT_SELECTORS = ('textarea', '[contenteditable="true"]')
REPLY_BUTTON_SELECTORS = (
    "button[data-action='reply']",
    'button:has-text("Ответить")',
    'button:has-text("Опубликовать")',
    'button:has-text("Отправить")',
)


class OzonClient:
    def __init__(self, storage_state, reviews_url):
        self.storage_state, self.reviews_url = Path(storage_state), reviews_url
        self._playwright = self._browser = self._page = None
        self.operation_lock = asyncio.Lock()

    async def start(self):
        async with self.operation_lock:
            await self._start_unlocked()

    async def _start_unlocked(self):
        if self._page:
            return
        if not self.storage_state.exists():
            raise SessionExpiredError(f'Файл browser-session не найден: {self.storage_state}')
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        context = await self._browser.new_context(storage_state=str(self.storage_state))
        self._page = await context.new_page()

    async def close(self):
        async with self.operation_lock:
            await self._close_unlocked()

    async def _close_unlocked(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._playwright = self._browser = self._page = None

    async def restart(self):
        async with self.operation_lock:
            await self._close_unlocked()
            await self._start_unlocked()

    async def fetch_unanswered(self):
        async with self.operation_lock:
            if not self._page:
                raise OzonError('Ozon client не запущен')
            await self._validate_session_unlocked()
            cards, selector = await self._find_review_cards()
            result = []
            for item in await cards.all():
                if await self._is_answered(item):
                    continue
                review_id = await self._first_attribute(item, 'data-review-id', 'data-id', 'id')
                if not review_id:
                    continue
                text = (await item.inner_text()).strip()
                rating = await self._rating(item, text)
                result.append({
                    'review_id': review_id,
                    'rating': rating,
                    'text': text,
                    'product_name': await self._first_attribute(item, 'data-product-name'),
                })
            if selector == 'article' and await cards.count() and not result:
                raise SelectorChangedError('Ozon: карточки найдены, но их ID не распознан; интерфейс мог измениться')
            return result

    async def validate_session(self):
        async with self.operation_lock:
            await self._validate_session_unlocked()

    async def _validate_session_unlocked(self):
        if not self._page:
            raise OzonError('Ozon client не запущен')
        await self._page.goto(self.reviews_url, wait_until='domcontentloaded')
        current_url = self._page.url.lower()
        if 'login' in current_url or 'auth' in current_url:
            raise SessionExpiredError('Сессия Ozon истекла. Подключите Ozon заново через кнопку в боте.')

    async def publish_reply(self, review_id, text):
        async with self.operation_lock:
            if not self._page:
                raise OzonError('Ozon client не запущен')
            card = self._page.locator(
                f"[data-review-id='{review_id}'], [data-id='{review_id}']"
            )
            if await card.count() == 0:
                raise SelectorChangedError('Ozon: карточка отзыва не найдена; интерфейс мог измениться')
            input_locator = await self._first_visible(card, REPLY_INPUT_SELECTORS)
            button_locator = await self._first_visible(card, REPLY_BUTTON_SELECTORS)
            if input_locator is None or button_locator is None:
                raise SelectorChangedError('Ozon: не найдено поле или кнопка ответа; интерфейс мог измениться')
            try:
                await input_locator.fill(text)
                await button_locator.click()
                await self._wait_for_published(card)
            except SelectorChangedError:
                raise
            except Exception as exc:
                raise OzonError('Не удалось опубликовать ответ в Ozon') from exc

    async def _save_error_screenshot(self, prefix: str = "error") -> None:
        if not self._page or not hasattr(self._page, "screenshot"):
            return
        try:
            screenshots_dir = Path("storage/screenshots")
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            path = screenshots_dir / f"{prefix}_{int(asyncio.get_running_loop().time())}.png"
            await self._page.screenshot(path=str(path), full_page=True)
        except Exception:
            pass

    async def _find_review_cards(self):
        for selector in REVIEW_CARD_SELECTORS:
            locator = self._page.locator(selector)
            if await locator.count():
                return locator, selector
        await self._save_error_screenshot("cards_not_found")
        raise SelectorChangedError('Ozon: не найден локатор карточек отзывов; интерфейс мог измениться')

    async def _is_answered(self, item):
        if await item.locator("[data-answered='true']").count():
            return True
        text = (await item.inner_text()).lower()
        return 'ответ опубликован' in text or 'ваш ответ' in text

    async def _first_attribute(self, item, *names):
        for name in names:
            value = await item.get_attribute(name)
            if value:
                return value
        return None

    async def _rating(self, item, text):
        value = await item.get_attribute('data-rating')
        try:
            return max(0, min(5, int(value or 0)))
        except ValueError:
            return max(0, min(5, len(re.findall(r'★', text))))

    async def _first_visible(self, parent, selectors):
        for selector in selectors:
            locator = parent.locator(selector)
            if await locator.count():
                return locator.first
        return None

    async def _wait_for_published(self, card):
        for selector in ("[data-answered='true']", 'button:has-text("Изменить ответ")'):
            locator = card.locator(selector)
            if await locator.count():
                await locator.first.wait_for(timeout=10000)
                return
        await self._save_error_screenshot("publish_wait_failed")
        raise SelectorChangedError('Ozon: не найден признак опубликованного ответа')
