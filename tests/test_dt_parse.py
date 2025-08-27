# -*- coding: utf-8 -*-
from src.handlers.booking import _try_parse_dt_ru

def test_parse_ru_relative():
    dt = _try_parse_dt_ru("завтра 12:30", "Asia/Yekaterinburg")
    assert dt is not None
    assert dt.hour == 12 and dt.minute == 30

def test_parse_ru_absolute():
    dt = _try_parse_dt_ru("24.08 09:05", "Asia/Yekaterinburg")
    assert dt is not None
    assert dt.hour == 9 and dt.minute == 5
