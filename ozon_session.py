import json
import os
import tempfile
from pathlib import Path

MAX_STORAGE_STATE_BYTES = 5 * 1024 * 1024


class SessionFileError(ValueError):
    pass


def normalize_storage_state(raw: bytes | str) -> dict:
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if len(raw) > MAX_STORAGE_STATE_BYTES:
        raise SessionFileError('Файл сессии слишком большой (максимум 5 МБ).')
    try:
        text = raw.decode('utf-8-sig').strip()
        data = json.loads(text)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionFileError('Данные должны быть корректным JSON (в .json или .txt файле).') from exc

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
