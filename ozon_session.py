import json
import os
import tempfile
from pathlib import Path

MAX_STORAGE_STATE_BYTES = 5 * 1024 * 1024


class SessionFileError(ValueError):
    pass


class OzonLoginWizard:
    """Interactive login for a bot process running on the manager's PC."""

    def __init__(self, reviews_url: str):
        self.reviews_url = reviews_url
        self._playwright = self._browser = self._context = self._page = None

    async def start(self):
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=False)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        await self._page.goto('https://seller.ozon.ru/', wait_until='domcontentloaded')

    async def save(self, target: str | Path):
        if not self._page or not self._context:
            raise SessionFileError('Окно входа Ozon не запущено.')
        await self._page.goto(self.reviews_url, wait_until='domcontentloaded')
        current_url = self._page.url.lower()
        if 'login' in current_url or 'auth' in current_url:
            raise SessionFileError('Вход ещё не завершён. Войдите в Ozon и нажмите «Я вошёл».')
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as file:
            temporary_path = Path(file.name)
        try:
            await self._context.storage_state(path=str(temporary_path))
            save_storage_state(temporary_path.read_bytes(), target)
        finally:
            temporary_path.unlink(missing_ok=True)

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._playwright = self._browser = self._context = self._page = None


def normalize_storage_state(raw: bytes | str) -> dict:
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if len(raw) > MAX_STORAGE_STATE_BYTES:
        raise SessionFileError('Файл сессии слишком большой (максимум 5 МБ).')
    try:
        data = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionFileError('Данные должны быть корректным JSON.') from exc

    if isinstance(data, dict):
        if 'cookies' not in data or not isinstance(data.get('cookies'), list):
            raise SessionFileError('Нераспознанный JSON: требуется список cookies или массив кук.')
        origins = data.get('origins', [])
        return {
            'cookies': _normalize_cookies(data['cookies']),
            'origins': origins if isinstance(origins, list) else [],
        }

    if isinstance(data, list):
        if not data:
            raise SessionFileError('Список cookies пуст.')
        return {
            'cookies': _normalize_cookies(data),
            'origins': [],
        }

    raise SessionFileError('Нераспознанный формат: отправьте файл ozon_state.json или JSON-экспорт cookies.')


def _normalize_cookies(raw_cookies: list) -> list[dict]:
    normalized = []
    for item in raw_cookies:
        if not isinstance(item, dict) or not item.get('name') or item.get('value') is None:
            continue
        same_site = str(item.get('sameSite', 'Lax')).lower()
        if same_site in ('strict',):
            same_site_val = 'Strict'
        elif same_site in ('none', 'no_restriction'):
            same_site_val = 'None'
        else:
            same_site_val = 'Lax'

        expires = item.get('expires')
        if expires is None:
            expires = item.get('expirationDate')
        if expires is not None:
            try:
                expires = int(float(expires))
            except (ValueError, TypeError):
                expires = -1
        else:
            expires = -1

        normalized.append({
            'name': str(item['name']),
            'value': str(item['value']),
            'domain': str(item.get('domain', '.ozon.ru')),
            'path': str(item.get('path', '/')),
            'expires': expires,
            'httpOnly': bool(item.get('httpOnly', False)),
            'secure': bool(item.get('secure', True)),
            'sameSite': same_site_val,
        })
    return normalized


def save_storage_state(raw: bytes | str, target: str | Path) -> None:
    state = normalize_storage_state(raw)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent, delete=False) as file:
        json.dump(state, file, ensure_ascii=False, separators=(',', ':'))
        temporary_path = Path(file.name)
    try:
        temporary_path.chmod(0o600)
        os.replace(temporary_path, target)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
