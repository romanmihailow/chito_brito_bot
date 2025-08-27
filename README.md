# Чито-Брито — Telegram-бот записи (aiogram v3 + Google Sheets + OpenAI KB)

## Быстрый старт (локально, polling)
1. Скопируйте `.env.example` в `.env` и заполните:
   - `TELEGRAM_BOT_TOKEN` — токен бота (не храните в репозитории).
   - `ADMIN_IDS` — Telegram ID админов (через запятую).
   - `GOOGLE_SHEETS_SPREADSHEET_ID` — ваш Spreadsheet ID.
   - `GOOGLE_APPLICATION_CREDENTIALS` — путь к JSON сервисного аккаунта (в контейнере — `/app/secrets/xxx.json`).
   - `KB_GOOGLE_DOC_ID` — Doc ID базы знаний (дайте доступ сервисному аккаунту).
   - `OPENAI_API_KEY` — ключ OpenAI (для KB/ASR), можно оставить пустым — тогда ответ по KB будет ограничен.
2. Установите зависимости и запустите:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python app.py
