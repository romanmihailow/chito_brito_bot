# -*- coding: utf-8 -*-
import logging
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

try:
    from pytz import timezone as _tz  # для явной TZ
except Exception:
    _tz = None

log = logging.getLogger("scheduler")

# Глобальная ссылка на планировщик, чтобы корректно останавливать
_scheduler: Optional[AsyncIOScheduler] = None


# =========================
# Джобы
# =========================
async def _job_heartbeat():
    log.info("Пульс 🫀")


async def _job_nightly(dp, repo, tz_name: str):
    """
    Ночная задача:
    - гарантирует наличие 14 дней вкладок слева направо (самая дальняя слева)
    - при необходимости обновляет шапки дат
    """
    try:
        if hasattr(repo, "ensure_future_days_desc"):
            created, ordered = repo.ensure_future_days_desc(days=14)  # type: ignore
            log.info("Night ensure: created=%s; order=%s", created, ordered)
        elif hasattr(repo, "roll_day_sheets"):
            # Фолбэк на старую реализацию
            repo.roll_day_sheets(horizon_days=14)  # type: ignore
            log.info("Night ensure (fallback roll_day_sheets) ok")
    except Exception:
        log.exception("Night ensure failed")


# =========================
# API
# =========================
async def start_scheduler(*, dp, repo, tz_name: str, horizon_days: int = 14):
    """Запуск APScheduler и регистрация задач."""
    global _scheduler
    if _scheduler:
        return _scheduler

    tz = _tz(tz_name) if _tz else None
    _scheduler = AsyncIOScheduler(timezone=tz)

    # Пульс каждые 5 минут
    _scheduler.add_job(_job_heartbeat, IntervalTrigger(minutes=5), id="heartbeat")

    # Ночная проверка в 00:00 локального времени
    _scheduler.add_job(
        _job_nightly,
        CronTrigger(hour=0, minute=0),
        kwargs={"dp": dp, "repo": repo, "tz_name": tz_name},
        id="night_ensure",
    )

    _scheduler.start()
    log.info("APScheduler: запущен (%s)", tz_name)

    # Одноразовый прогон при старте (чтобы не ждать ночи)
    try:
        await _job_nightly(dp, repo, tz_name)
    except Exception:
        log.exception("Startup night ensure failed")

    return _scheduler


async def stop_scheduler():
    """Мягкая остановка планировщика (используется при завершении бота)."""
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        finally:
            _scheduler = None
