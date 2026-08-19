# Ozon Reviews Bot

Внутренний Telegram-бот для менеджеров магазина. Доступ открывается командой `/auth <пароль>`.

## Запуск

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e .
playwright install chromium
cp .env.example .env
python create_ozon_session.py
python main.py
```

Заполните `TELEGRAM_TOKEN`, `AUTH_PASSWORD` и `LLM_API_KEY` в `.env`. Логин, пароль, CAPTCHA и 2FA в коде не автоматизируются: `create_ozon_session.py` открывает браузер для ручного входа и сохраняет `storage_state`.

CSV/XLSX для примеров должен содержать непустую колонку `reply`; `review` необязательна. SQLite хранится в `DATABASE_PATH` и переживает перезапуски.

