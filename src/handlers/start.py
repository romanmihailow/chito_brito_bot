# -*- coding: utf-8 -*-
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

router = Router()

@router.message(F.text == "/start")
async def start_cmd(msg: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Записаться"), KeyboardButton(text="Мои записи")],
            [KeyboardButton(text="Услуги и цены"), KeyboardButton(text="Мастера")],
            [KeyboardButton(text="Контакты"), KeyboardButton(text="FAQ"), KeyboardButton(text="Отзывы")],
        ],
        resize_keyboard=True
    )
    await msg.answer(
        "Привет! Это бот записи «Чито-Брито». Нажми «Записаться», чтобы выбрать услугу — или «Мои записи», чтобы посмотреть заявки.",
        reply_markup=kb
    )
