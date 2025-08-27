# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, List, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

class InjectStuffMiddleware(BaseMiddleware):
    def __init__(
        self,
        *,
        repo,
        admin_ids: List[int],
        tz_name: str,
        openai_api_key: Optional[str],
        openai_transcribe_model: str,
        cfg: Dict[str, Any],
        kb
    ):
        self.repo = repo
        self.admin_ids = admin_ids
        self.tz_name = tz_name
        self.openai_api_key = openai_api_key
        self.openai_transcribe_model = openai_transcribe_model
        self.cfg = cfg
        self.kb = kb

    async def __call__(self, handler, event: TelegramObject, data: Dict[str, Any]) -> Any:
        # data["dispatcher"] — общее место, куда будем складывать зависимости
        data.setdefault("dispatcher", {})
        d = data["dispatcher"]
        d["repo"] = self.repo
        d["admin_ids"] = self.admin_ids
        d["tz_name"] = self.tz_name
        d["openai_api_key"] = self.openai_api_key
        d["openai_transcribe_model"] = self.openai_transcribe_model
        d["cfg"] = self.cfg
        d["kb"] = self.kb
        return await handler(event, data)
