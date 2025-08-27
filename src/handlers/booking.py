# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.sheets_repo import SheetsRepo

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # type: ignore

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

log = logging.getLogger(__name__)
router = Router(name="booking")


class BookingStates(StatesGroup):
    waiting_time_wish = State()


@dataclass
class ServiceItem:
    slug: str
    name: str
    price: int = 0
    addon_only: bool = False
    active: bool = True


INTENT_SYNONYMS = {
    "book": {
        "записаться", "запись", "хочу записаться", "оформить запись", "запиши",
        "записать меня", "сделать запись", "записи", "на запись", "запишись",
    },
    "my": {
        "мои записи", "мои заявки", "заявки мои", "записи мои", "мои брони",
        "мои визиты", "мои", "заявки", "записи", "мои услуги",
    },
    "help": {"старт", "start", "меню", "помощь", "help", "/start"},
}


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\sёа-я-]", " ", s.lower())).strip()


def _is_intent(text: str, intent: str) -> bool:
    t = _normalize(text)
    for phrase in INTENT_SYNONYMS.get(intent, set()):
        if _normalize(phrase) in t or t == _normalize(phrase):
            return True
    return False


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Записаться", callback_data="go:book")
    kb.button(text="Мои записи", callback_data="go:my:0")
    kb.button(text="Услуги и цены", callback_data="go:prices")
    kb.button(text="Мастера", callback_data="go:masters")
    kb.button(text="Контакты", callback_data="go:contacts")
    kb.button(text="FAQ", callback_data="go:faq")
    kb.button(text="Отзывы", callback_data="go:reviews")
    kb.adjust(2, 2, 3)
    return kb.as_markup()


def _services_kb(items: List[ServiceItem], page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    start = max(0, page * page_size)
    chunk = items[start: start + page_size]

    kb = InlineKeyboardBuilder()
    for it in chunk:
        label = f"{it.name} • {it.price:,} ₽".replace(",", " ")
        kb.button(text=label, callback_data=f"svc:{it.slug}")
    rows = max(1, len(chunk))
    kb.adjust(*([1] * rows))

    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    if total_pages > 1:
        nav = InlineKeyboardBuilder()
        if page > 0:
            nav.button(text="⬅︎ Назад", callback_data=f"svcnav:{page-1}")
        nav.button(text=f"{page+1}/{total_pages}", callback_data="noop")
        if page + 1 < total_pages:
            nav.button(text="Вперёд ➜", callback_data=f"svcnav:{page+1}")
        nav.adjust(3 if (page > 0 and page + 1 < total_pages) else 2)
        kb.attach(nav)

    return kb.as_markup()


def _my_kb(items: List[Dict[str, str]], offset: int, has_next: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for idx, r in enumerate(items, start=offset + 1):
        status = (r.get("status") or "").lower()
        if status not in {"cancelled", "canceled", "done", "completed"}:
            kb.button(text=f"❌ Отменить {idx}", callback_data=f"cancel:{r.get('_row')}")

    kb.button(text="Обновить ↻", callback_data=f"go:my:{offset}")
    if offset > 0:
        kb.button(text="Назад", callback_data=f"go:my:{max(0, offset-5)}")
    if has_next:
        kb.button(text="Вперёд ➜", callback_data=f"go:my:{offset+5}")
    kb.button(text="Записаться", callback_data="go:book")
    kb.adjust(2, 2, 2)
    return kb.as_markup()


def _services_from_repo(repo: SheetsRepo) -> List[ServiceItem]:
    raw = repo.get_services()
    items: List[ServiceItem] = []
    for slug, s in raw.items():
        if not s.get("active", True):
            continue
        if s.get("addon_only", False):
            continue
        price = 0
        try:
            price = int(float(s.get("base_price", 0) or 0))
        except Exception:
            price = 0
        items.append(ServiceItem(slug=slug, name=s.get("name", slug), price=price))
    items.sort(key=lambda x: x.name.lower())
    return items


def _match_service(repo: SheetsRepo, text: str) -> Optional[ServiceItem]:
    t = _normalize(text)
    best: Optional[ServiceItem] = None
    for it in _services_from_repo(repo):
        name_norm = _normalize(it.name)
        slug_norm = _normalize(it.slug)
        if name_norm and name_norm in t:
            return it
        if slug_norm and slug_norm in t:
            best = it
    return best


def _get_tz(tz_name: str):
    if ZoneInfo:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    return None


_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

def _try_parse_dt_ru(text: str, tz_name: str) -> Optional[datetime]:
    t = text.lower().strip()
    m_time = re.search(r"(\d{1,2})[:\.](\d{2})", t)
    if not m_time:
        return None
    hh, mm = int(m_time.group(1)), int(m_time.group(2))
    if hh > 23 or mm > 59:
        return None

    tz = _get_tz(tz_name)
    now = datetime.now(tz=tz) if tz else datetime.utcnow()
    base = now.date()

    if "послезавтра" in t:
        base = (now + timedelta(days=2)).date()
    elif "завтра" in t:
        base = (now + timedelta(days=1)).date()
    elif "сегодня" in t:
        base = now.date()
    else:
        m_dm = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b", t)
        if m_dm:
            d, m = int(m_dm.group(1)), int(m_dm.group(2))
            y = int(m_dm.group(3)) if m_dm.group(3) else now.year
            try:
                base = datetime(y, m, d).date()
            except Exception:
                pass
        else:
            m_rus = re.search(
                r"\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(\d{4}))?",
                t,
            )
            if m_rus:
                d = int(m_rus.group(1))
                mon = _MONTHS[m_rus.group(2)]
                y = int(m_rus.group(3)) if m_rus.group(3) else now.year
                try:
                    base = datetime(y, mon, d).date()
                except Exception:
                    pass

    candidate = datetime(base.year, base.month, base.day, hh, mm, tzinfo=tz) if tz else datetime(
        base.year, base.month, base.day, hh, mm
    )
    if not any(w in t for w in ("сегодня", "завтра", "послезавтра")) \
       and not re.search(r"\d{1,2}[.\-/]\d{1,2}", t) \
       and not re.search(r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)", t):
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
    return candidate

def _validate_future_wish(wish: str, tz_name: str) -> Tuple[bool, Optional[str]]:
    dt = _try_parse_dt_ru(wish, tz_name)
    if not dt:
        return True, None
    now = datetime.now(tz=dt.tzinfo) if dt.tzinfo else datetime.utcnow()
    if dt < now - timedelta(minutes=5):
        return False, "Похоже, это время уже прошло. Укажите, пожалуйста, другую дату/время."
    return True, None

def _oa_client(api_key: Optional[str]):
    if not api_key or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None

async def _recognize_voice(message: Message, api_key: Optional[str], model: str) -> Optional[str]:
    if not message.voice:
        return None
    client = _oa_client(api_key)
    if client is None:
        return None
    buf = io.BytesIO()
    try:
        file = await message.bot.get_file(message.voice.file_id)
        await message.bot.download(file, destination=buf)
        buf.seek(0)
        resp = client.audio.transcriptions.create(
            model=model or "whisper-1",
            file=("voice.ogg", buf, "audio/ogg"),
        )
        text = getattr(resp, "text", None)
        log.info("Voice recognized: %s", text)
        return text.strip() if text else None
    except Exception as e:
        log.exception("Ошибка распознавания голоса: %s", e)
        return None

async def _append_request(repo: SheetsRepo, message: Message, service_slug: str, wish_text: str):
    svc = repo.get_services().get(service_slug, {})
    svc_name = svc.get("name", service_slug)
    u = message.from_user
    payload = {
        "tg_user_id": u.id if u else "",
        "tg_username": f"@{u.username}" if (u and u.username) else "",
        "tg_fullname": (u.full_name if u else "").strip(),
        "service_slug": service_slug,
        "service_name": svc_name,
        "wish_text": wish_text,
        "chat_id": message.chat.id,
    }
    await repo.add_request_async(payload)

async def _render_my_list(repo: SheetsRepo, tg_user_id: int, offset: int = 0):
    rows = await repo.list_requests_by_user_async(tg_user_id=tg_user_id, limit=20, offset=0)
    rows = [r for r in rows if (r.get("status","").lower() not in {"cancelled","canceled","done","completed"})]
    view = rows[offset: offset+6]
    has_next = len(rows) > offset + 5
    if not view:
        return "У вас пока нет заявок. Нажмите «Записаться», чтобы выбрать услугу.", [], False
    parts = ["<b>Ваши заявки</b>"]
    for i, r in enumerate(view, start=offset + 1):
        svc = r.get("service_name") or r.get("service_slug")
        wish = r.get("wish_text") or "—"
        status = r.get("status") or "new"
        ts = r.get("ts") or ""
        parts.append(f"{i}. <b>{svc}</b> • ⏱ {wish} • Статус: <i>{status}</i> • [{ts}]")
    return "\n".join(parts), view, has_next


@router.message(CommandStart())
async def on_start(message: Message, **kwargs):
    await message.answer(
        "Привет! Это бот записи «Чито-Брито». Нажмите «Записаться», чтобы выбрать услугу — или «Мои записи», чтобы посмотреть заявки.",
        reply_markup=main_menu_kb(),
    )

@router.callback_query(F.data == "go:book")
async def go_book(cb: CallbackQuery, **kwargs):
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    services = _services_from_repo(repo)
    await cb.message.answer(
        "Выберите услугу (кнопкой ниже) — или пришлите её название сообщением:",
        reply_markup=_services_kb(services, page=0),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("svcnav:"))
async def svc_nav(cb: CallbackQuery, **kwargs):
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    services = _services_from_repo(repo)
    page = int(cb.data.split(":")[1])
    await cb.message.edit_reply_markup(reply_markup=_services_kb(services, page=page))
    await cb.answer()

@router.callback_query(F.data.startswith("svc:"))
async def svc_pick(cb: CallbackQuery, state: FSMContext, **kwargs):
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    slug = cb.data.split(":", 1)[1]
    svc = repo.get_services().get(slug, {})
    name = svc.get("name", slug)
    await state.update_data(service_slug=slug)
    await state.set_state(BookingStates.waiting_time_wish)
    log.info("state->waiting_time_wish; service=%s", slug)
    await cb.message.answer(
        f"Вы выбрали: <b>{name}</b>. Напишите желаемые дату и время — например: <b>«завтра 19:00»</b> или <b>«24.09 15:30»</b>.",
    )
    await cb.answer()

async def _route_text_core(message: Message, state: FSMContext, *, text: str, **kwargs):
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    kb = kwargs["dispatcher"]["kb"]

    txt = (text or "").strip()
    if not txt:
        return

    # «мои записи»
    if _is_intent(txt, "my"):
        out, items, has_next = await _render_my_list(repo, message.from_user.id, offset=0)
        await message.answer(out, reply_markup=_my_kb(items, 0, has_next))
        return

    # «записаться …»
    if _is_intent(txt, "book"):
        svc = _match_service(repo, txt)
        if svc:
            await state.update_data(service_slug=svc.slug)
            await state.set_state(BookingStates.waiting_time_wish)
            await message.answer(
                f"Вы выбрали: <b>{svc.name}</b>. Укажите желаемые дату и время (например «завтра 19:00»)."
            )
            return
        services = _services_from_repo(repo)
        await message.answer(
            "Выберите услугу (кнопкой ниже) — или пришлите её название:",
            reply_markup=_services_kb(services, page=0),
        )
        return

    # просто написал название услуги
    svc = _match_service(repo, txt)
    if svc:
        await state.update_data(service_slug=svc.slug)
        await state.set_state(BookingStates.waiting_time_wish)
        await message.answer(
            f"Вы выбрали: <b>{svc.name}</b>. Укажите желаемые дату и время (например «завтра 19:00»)."
        )
        return

    # help
    if _is_intent(txt, "help"):
        await message.answer("Главное меню:", reply_markup=main_menu_kb())
        return

    # если мы сейчас ждём время — не отвлекаемся на свободные вопросы
    if await state.get_state() == BookingStates.waiting_time_wish.state:
        return

    # Иначе — ответим по внутренним данным (без упоминаний источников)
    answer, _ref = kb.answer(txt)
    await message.answer(answer, reply_markup=main_menu_kb())

@router.message(F.text)
async def router_text(message: Message, state: FSMContext, **kwargs):
    await _route_text_core(message, state, text=(message.text or ""), **kwargs)

@router.message(F.voice)
async def router_voice(message: Message, state: FSMContext, **kwargs):
    api_key: Optional[str] = kwargs["dispatcher"]["openai_api_key"]
    model: str = kwargs["dispatcher"]["openai_transcribe_model"]
    if not api_key:
        await message.answer("Распознавание голоса сейчас выключено. Напишите, пожалуйста, текстом 🙂")
        return
    text = await _recognize_voice(message, api_key, model)
    if not text:
        await message.answer("Не удалось распознать голос. Напишите текстом, пожалуйста 🙂")
        return
    await message.answer(f"🎙️ Распознано: <i>{text}</i>")
    await _route_text_core(message, state, text=text, **kwargs)

@router.message(BookingStates.waiting_time_wish, F.text)
async def time_wish_text(message: Message, state: FSMContext, **kwargs):
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    admin_ids: List[int] = kwargs["dispatcher"]["admin_ids"]
    tz_name: str = kwargs["dispatcher"]["tz_name"]
    cfg = kwargs["dispatcher"]["cfg"]
    horizon_days = int(cfg.get("booking_horizon_days", 14))

    data = await state.get_data()
    slug = data.get("service_slug")
    if not slug:
        services = _services_from_repo(repo)
        await message.answer("Выберите услугу ниже:", reply_markup=_services_kb(services, page=0))
        await state.clear()
        return

    wish = (message.text or "").strip()

    # Требуем явное время
    if not re.search(r"\b\d{1,2}[:\.]\d{2}\b", wish):
        await message.answer("Пожалуйста, укажите время в формате <b>часы:минуты</b> — например: <b>19:00</b>.")
        return

    dt = _try_parse_dt_ru(wish, tz_name)
    if not dt:
        await message.answer("Не понял дату/время. Пример: <b>завтра 19:00</b> или <b>29.08 15:30</b>.")
        return

    now = datetime.now(tz=dt.tzinfo) if dt.tzinfo else datetime.utcnow()
    last_allowed = (now.date() + timedelta(days=horizon_days-1))
    if dt.date() > last_allowed:
        await message.answer(
            "Запись открыта на <b>14 дней</b> вперёд.\n"
            f"Можно выбрать дату до <b>{last_allowed.strftime('%d.%m.%Y')}</b> включительно."
        )
        return
    if dt < now - timedelta(minutes=5):
        await message.answer("Похоже, это время уже прошло. Укажите, пожалуйста, другое.")
        return

    await _append_request(repo, message, slug, wish)

    svc_name = repo.get_services().get(slug, {}).get("name", slug)

    ru_wdays = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
    wday = ru_wdays[dt.weekday()]
    wish_view = f"{wday}, {dt.strftime('%d.%m.%Y')} в {dt.strftime('%H:%M')}"
    u = message.from_user
    uname = f"@{u.username}" if (u and u.username) else ""
    fname = (u.full_name if u else "").strip()

    text_user = (
        "✅ <b>Заявка отправлена</b>\n"
        f"🧾 Услуга: <b>{svc_name}</b>\n"
        f"🗓️ Время: <b>{wish_view}</b>\n"
        f"👤 Клиент: {fname} {uname}\n\n"
        "Администратор подберёт ближайшее свободное окно и подтвердит в чате.\n"
        "📍 «Чито-Брито», Уфа\n"
        "☎️ +7 927 949-50-26"
    )
    await message.answer(text_user, reply_markup=main_menu_kb())

    if admin_ids:
        try:
            admin_text = (
                "🆕 <b>Заявка</b>\n"
                f"🧾 Услуга: <b>{svc_name}</b>\n"
                f"🗓️ Пожелание: <b>{wish_view}</b>\n"
                f"👤 Клиент: <b>{fname}</b> {uname} (id={u.id if u else '-'})\n"
                f"📱 Телефон: —"
            )
            for aid in admin_ids:
                await message.bot.send_message(aid, admin_text)
        except Exception:
            pass

    await state.clear()

@router.callback_query(F.data.startswith("go:my:"))
async def my_bookings_cb(cb: CallbackQuery, **kwargs):
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    try:
        offset = int(cb.data.split(":", 2)[2])
    except Exception:
        offset = 0
    text, items, has_next = await _render_my_list(repo, cb.from_user.id, offset=offset)
    await cb.message.answer(text, reply_markup=_my_kb(items, offset, has_next))
    await cb.answer()

@router.callback_query(F.data.startswith("cancel:"))
async def cancel_request_cb(cb: CallbackQuery, **kwargs):
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    admin_ids: List[int] = kwargs["dispatcher"]["admin_ids"]

    try:
        row = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer("Не получилось отменить")
        return

    req = await repo.get_request_by_row_async(row)
    await repo.update_request_status_async(row, "cancelled")

    await cb.answer("Отменено")
    await cb.message.answer("Заявка отменена. Если нужно — оформите новую.", reply_markup=main_menu_kb())

    text, items, has_next = await _render_my_list(repo, cb.from_user.id, offset=0)
    await cb.message.answer(text, reply_markup=_my_kb(items, 0, has_next))

    if req and admin_ids:
        try:
            for aid in admin_ids:
                await cb.bot.send_message(
                    aid,
                    "❌ <b>Клиент отменил заявку</b>\n"
                    f"Клиент: <b>{req.get('tg_fullname','')}</b> {req.get('tg_username','')}\n"
                    f"Услуга: <b>{req.get('service_name') or req.get('service_slug')}</b>\n"
                    f"Пожелание: <b>{req.get('wish_text') or '—'}</b>\n"
                    f"Строка Requests: {row}",
                )
        except Exception:
            pass

@router.callback_query(F.data == "go:prices")
async def go_prices(cb: CallbackQuery, **kwargs):
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    items = _services_from_repo(repo)
    if not items:
        await cb.message.answer("Лист Services пуст. Добавьте услуги.")
    else:
        lines = ["<b>Услуги и цены</b>"]
        for it in items:
            lines.append(f"• {it.name} — <b>{it.price:,} ₽</b>".replace(",", " "))
        await cb.message.answer("\n".join(lines))
    await cb.answer()

@router.callback_query(F.data == "go:masters")
async def go_masters(cb: CallbackQuery, **kwargs):
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    m = repo.get_masters()
    if not m:
        await cb.message.answer("Список мастеров пуст. Откройте лист Masters.")
    else:
        lines = ["<b>Мастера</b>"]
        for k, v in m.items():
            lines.append(f"• {v.get('full_name','Без имени')} — {v.get('role','')}")
        await cb.message.answer("\n".join(lines))
    await cb.answer()

@router.callback_query(F.data == "go:contacts")
async def go_contacts(cb: CallbackQuery, **kwargs):
    await cb.message.answer(
        "Салон «Чито-Брито» • Уфа\n"
        "2ГИС: https://2gis.ru/ufa/firm/70000001040326897\n"
        "Телефон: +7 927 949-50-26"
    )
    await cb.answer()

@router.callback_query(F.data == "go:faq")
async def go_faq(cb: CallbackQuery, **kwargs):
    # Ответим базово, а остальное пусть спрашивают текстом
    await cb.message.answer(
        "<b>FAQ</b>\n"
        "• Как записаться? — Нажмите «Записаться» и выберите услугу.\n"
        "• Можно голосом? — Да, скажите «завтра в 17:00 мужская стрижка».\n"
        "• Отмена? — В разделе «Мои записи».\n\n"
        "Можете задать вопрос сообщением — отвечу."
    )
    await cb.answer()

@router.callback_query(F.data == "go:reviews")
async def go_reviews(cb: CallbackQuery, **kwargs):
    await cb.message.answer("Отзывы можно оставить в 2ГИС или здесь в чате — мы читаем всё ❤️")
    await cb.answer()
