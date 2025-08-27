# -*- coding: utf-8 -*-
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from src.sheets_repo import SheetsRepo

router = Router()

ADMIN_IDS = set([x.strip() for x in os.getenv("ADMIN_IDS","").split(",") if x.strip()])

def is_admin(user_id: int) -> bool:
    return str(user_id) in ADMIN_IDS

@router.message(F.text == "/admin")
async def admin_menu(msg: Message, **kwargs):
    if not is_admin(msg.from_user.id):
        return await msg.answer("Доступ запрещён.")
    kb = InlineKeyboardBuilder()
    kb.button(text="Перечитать конфиг", callback_data="admin:reload")
    kb.button(text="Показать статус", callback_data="admin:status")
    kb.button(text="Заполнить 14 дней слева", callback_data="admin:fill_left_14")
    kb.adjust(1)
    await msg.answer("Админ-панель:", reply_markup=kb.as_markup())

@router.callback_query(F.data == "admin:reload")
async def admin_reload(call: CallbackQuery, **kwargs):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа.", show_alert=True)
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    repo.force_reload_all()
    await call.answer("Ок")
    await call.message.edit_text("Конфиг и справочники перечитаны ✅")

@router.callback_query(F.data == "admin:status")
async def admin_status(call: CallbackQuery, **kwargs):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа.", show_alert=True)
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    cfg = kwargs["dispatcher"]["cfg"]
    await call.answer("Ок")
    await call.message.edit_text(
        "Статус:\n"
        f"• TZ: {kwargs['dispatcher']['tz_name']}\n"
        f"• Горизонт записи: {cfg.get('booking_horizon_days', 14)} дней\n"
        f"• Ресурсы: {repo.get_config().get('resources',{}) if hasattr(repo,'get_config') else '{}'}\n"
        f"• Запись включена: {'Да' if True else 'Да'}"
    )

@router.callback_query(F.data == "admin:fill_left_14")
async def admin_fill_left(call: CallbackQuery, **kwargs):
    if not is_admin(call.from_user.id):
        return await call.answer("Нет доступа.", show_alert=True)
    await call.answer("Запускаю…")  # важно ответить сразу
    repo: SheetsRepo = kwargs["dispatcher"]["repo"]
    created, order = repo.ensure_future_days_desc(how_many=14)
    await call.message.answer(f"Готово ✅\nСоздано: {created}\nПорядок (слева→направо): {order}")
