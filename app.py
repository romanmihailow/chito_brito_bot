# -*- coding: utf-8 -*-
import asyncio
import logging
import os
from dataclasses import dataclass
from typing import List

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from dotenv import load_dotenv


from src.sheets_repo import SheetsRepo
from src.scheduler import start_scheduler, stop_scheduler

from src.middlewares import InjectStuffMiddleware
from src.handlers import start as start_handlers
from src.handlers import booking as booking_handlers
from src.handlers import admin as admin_handlers
from src.kb_index import KnowledgeBase

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

@dataclass
class Cfg:
    token: str
    spreadsheet_id: str
    gcred_path: str
    timezone: str
    booking_horizon_days: int
    admin_ids: List[int]
    openai_key: str
    openai_transcribe_model: str
    kb_doc_id: str

def read_cfg() -> Cfg:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
    gcred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    timezone = os.getenv("TIMEZONE", "Asia/Yekaterinburg").strip()
    horizon = int(os.getenv("HORIZON_DAYS", "14"))
    admin_ids = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x]
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_transcribe = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()
    kb_doc_id = os.getenv("KNOWLEDGE_DOC_ID", "1sLseCV3tEt3ukxS6wtbtl9G8HZIjv_H0bYY9lSHYoj0").strip()
    return Cfg(
        token=token,
        spreadsheet_id=spreadsheet_id,
        gcred_path=gcred,
        timezone=timezone,
        booking_horizon_days=horizon,
        admin_ids=admin_ids,
        openai_key=openai_key,
        openai_transcribe_model=openai_transcribe,
        kb_doc_id=kb_doc_id
    )

async def main():
    cfg = read_cfg()
    if not cfg.token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN пустой")
    if not cfg.spreadsheet_id or not cfg.gcred_path:
        raise RuntimeError("Google Sheets не сконфигурирован (GOOGLE_SHEETS_SPREADSHEET_ID / GOOGLE_APPLICATION_CREDENTIALS)")

    # Repo (Google Sheets)
    repo = SheetsRepo(
        spreadsheet_id=cfg.spreadsheet_id,
        credentials_json_path=cfg.gcred_path,
        timezone=cfg.timezone
    )
    repo.force_reload_all()

    # Knowledge base (Google Docs + OpenAI + FAISS)
    kb = KnowledgeBase(
        credentials_json_path=cfg.gcred_path,
        doc_id=cfg.kb_doc_id,
        openai_api_key=cfg.openai_key
    )

    # Telegram
    bot = Bot(token=cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Routers
    dp.include_routers(
        start_handlers.router,
        booking_handlers.router,
        admin_handlers.router,
    )

    # Middleware: прокидываем полезные штуки во все хендлеры
    dp.update.middleware(InjectStuffMiddleware(
        repo=repo,
        admin_ids=cfg.admin_ids,
        tz_name=cfg.timezone,
        openai_api_key=cfg.openai_key,
        openai_transcribe_model=cfg.openai_transcribe_model,
        cfg={
            "booking_horizon_days": cfg.booking_horizon_days
        },
        kb=kb
    ))

    # Планировщик (ночная проверка на 14 дней + heartbeat)
    await start_scheduler(dp=dp, repo=repo, tz_name=cfg.timezone, horizon_days=cfg.booking_horizon_days)

    logging.getLogger("aiogram.dispatcher").info("Start polling")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
