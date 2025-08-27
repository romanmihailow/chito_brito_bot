# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

log = logging.getLogger("sheets_repo")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _hdr_map(header_row: List[str]) -> Dict[str, int]:
    m = {}
    for i, h in enumerate(header_row):
        key = str(h).strip().lower()
        m[key] = i
    return m

class SheetsRepo:
    def __init__(self, *, spreadsheet_id: str, credentials_json_path: str, timezone: str = "Asia/Yekaterinburg"):
        self.spreadsheet_id = spreadsheet_id
        self.timezone = timezone
        creds = Credentials.from_service_account_file(credentials_json_path, scopes=SCOPES)
        self.svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._services: Optional[Dict[str, Dict[str, Any]]] = None
        self._masters: Optional[Dict[str, Dict[str, Any]]] = None

    def force_reload_all(self) -> None:
        _ = self.get_services()
        _ = self.get_masters()

    # ---- Services (лист Services: slug, name, base_price, active, addon_only)
    def get_services(self) -> Dict[str, Dict[str, Any]]:
        if self._services is not None:
            return self._services
        try:
            vals = self._values_get("Services!A1:Z1000")
            if vals:
                hdr = _hdr_map([str(x) for x in vals[0]])
                if "slug" in hdr and "name" in hdr:
                    res: Dict[str, Dict[str, Any]] = {}
                    for r in vals[1:]:
                        if not r or len(r) <= hdr["slug"]:
                            continue
                        slug = str(r[hdr["slug"]]).strip()
                        if not slug:
                            continue
                        name = str(r[hdr.get("name", -1)]).strip() if hdr.get("name") is not None else slug
                        active_raw = str(r[hdr.get("active", -1)]).strip().lower() if hdr.get("active") is not None and hdr["active"] < len(r) else "true"
                        active = active_raw in ("1", "true", "да", "yes", "y")
                        base_price = 0.0
                        if "base_price" in hdr and hdr["base_price"] < len(r):
                            try:
                                base_price = float(str(r[hdr["base_price"]]).replace(" ", "").replace(",", "."))
                            except Exception:
                                base_price = 0.0
                        addon_only = False
                        if "addon_only" in hdr and hdr["addon_only"] < len(r):
                            addon_only = str(r[hdr["addon_only"]]).strip().lower() in ("1", "true", "да", "yes", "y")

                        res[slug] = {
                            "name": name or slug,
                            "base_price": base_price,
                            "addon_only": addon_only,
                            "active": active,
                        }
                    if res:
                        self._services = res
                        return res
        except Exception as e:
            log.warning("Services: не удалось прочитать лист Services: %s", e)

        self._services = {
            "haircut": {"name": "мужская стрижка", "base_price": 800, "active": True},
        }
        return self._services

    # ---- Masters
    def get_masters(self) -> Dict[str, Dict[str, Any]]:
        if self._masters is not None:
            return self._masters
        try:
            rng = "Masters!A1:D200"
            vals = self._values_get(rng)
            if not vals:
                self._ensure_sheet("Masters")
                self._values_update("Masters!A1", [["id", "full_name", "role", "coef_price"]])
                self._masters = {}
                return self._masters
            header = [c.strip().lower() for c in vals[0]]
            m: Dict[str, Dict[str, Any]] = {}
            for r in vals[1:]:
                if not r or not r[0]:
                    continue
                item = {}
                for i, key in enumerate(header):
                    if i < len(r):
                        item[key] = r[i]
                try:
                    coef = str(item.get("coef_price", "1")).replace(",", ".")
                    item["coef_price"] = float(coef)
                except Exception:
                    item["coef_price"] = 1.0
                m[str(r[0]).strip()] = item
            self._masters = m
            return m
        except Exception:
            log.exception("Ошибка чтения Masters")
            self._masters = {}
            return self._masters

    # ----- Requests
    async def add_request_async(self, payload: Dict[str, Any]) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.add_request, payload)

    def add_request(self, payload: Dict[str, Any]) -> None:
        self._ensure_sheet(
            "Requests",
            header=[
                "ts",
                "tg_user_id",
                "tg_username",
                "tg_fullname",
                "service_slug",
                "service_name",
                "wish_text",
                "chat_id",
                "status",
            ],
        )
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            ts,
            payload.get("tg_user_id", ""),
            payload.get("tg_username", ""),
            payload.get("tg_fullname", ""),
            payload.get("service_slug", ""),
            payload.get("service_name", ""),
            payload.get("wish_text", ""),
            payload.get("chat_id", ""),
            "new",
        ]
        self._values_append("Requests!A1", [row])

    async def list_requests_by_user_async(self, *, tg_user_id: int, limit: int = 5, offset: int = 0) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.list_requests_by_user, tg_user_id, limit, offset)

    def list_requests_by_user(self, tg_user_id: int, limit: int = 5, offset: int = 0) -> List[Dict[str, Any]]:
        self._ensure_sheet("Requests")
        vals = self._values_get("Requests!A2:I100000")
        items: List[Dict[str, Any]] = []
        for idx, r in enumerate(vals, start=2):
            if not r:
                continue
            obj = {
                "_row": idx,
                "ts": r[0] if len(r) > 0 else "",
                "tg_user_id": r[1] if len(r) > 1 else "",
                "tg_username": r[2] if len(r) > 2 else "",
                "tg_fullname": r[3] if len(r) > 3 else "",
                "service_slug": r[4] if len(r) > 4 else "",
                "service_name": r[5] if len(r) > 5 else "",
                "wish_text": r[6] if len(r) > 6 else "",
                "chat_id": r[7] if len(r) > 7 else "",
                "status": r[8] if len(r) > 8 else "",
            }
            items.append(obj)

        uid = str(tg_user_id)
        items = [x for x in items if str(x.get("tg_user_id", "")) == uid]

        def _key(x):
            try:
                return datetime.strptime(str(x.get("ts", "")), "%Y-%m-%d %H:%M:%S")
            except Exception:
                return datetime.min

        items.sort(key=_key, reverse=True)
        return items[offset: offset + max(1, limit)]

    async def update_request_status_async(self, row_index: int, status: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.update_request_status, row_index, status)

    def update_request_status(self, row_index: int, status: str) -> None:
        rng = f"Requests!I{row_index}"
        self._values_update(rng, [[status]])

    async def get_request_by_row_async(self, row_index: int) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_request_by_row, row_index)

    def get_request_by_row(self, row_index: int) -> Optional[Dict[str, Any]]:
        vals = self._values_get(f"Requests!A{row_index}:I{row_index}")
        if not vals or not vals[0]:
            return None
        r = vals[0]
        return {
            "ts": r[0] if len(r) > 0 else "",
            "tg_user_id": r[1] if len(r) > 1 else "",
            "tg_username": r[2] if len(r) > 2 else "",
            "tg_fullname": r[3] if len(r) > 3 else "",
            "service_slug": r[4] if len(r) > 4 else "",
            "service_name": r[5] if len(r) > 5 else "",
            "wish_text": r[6] if len(r) > 6 else "",
            "chat_id": r[7] if len(r) > 7 else "",
            "status": r[8] if len(r) > 8 else "",
            "_row": row_index,
        }

    # ---------- ротация листов с днями (вперёд от сегодняшней даты)
    def roll_day_sheets(self, *, horizon_days: int = 8) -> None:
        meta = self.svc.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        sheets = meta.get("sheets", [])
        titles = [s["properties"]["title"] for s in sheets]

        re_day = re.compile(r"^\d{2}-\d{2}-\d{4}$")
        day_titles = [t for t in titles if re_day.match(t)]
        day_titles.sort(key=lambda t: datetime.strptime(t, "%d-%m-%Y"))

        template_sheet_id = None
        if day_titles:
            latest_title = day_titles[-1]
            for s in sheets:
                if s["properties"]["title"] == latest_title:
                    template_sheet_id = s["properties"]["sheetId"]
                    break

        today = datetime.now().date()
        needed = [(today + timedelta(days=i)).strftime("%d-%m-%Y") for i in range(horizon_days)]
        to_create = [t for t in needed if t not in titles]

        for new_title in to_create:
            if template_sheet_id is not None:
                copy_resp = self.svc.spreadsheets().sheets().copyTo(
                    spreadsheetId=self.spreadsheet_id,
                    sheetId=template_sheet_id,
                    body={"destinationSpreadsheetId": self.spreadsheet_id},
                ).execute()
                new_id = copy_resp["sheetId"]
                self.svc.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": [{"updateSheetProperties": {
                        "properties": {"sheetId": new_id, "title": new_title},
                        "fields": "title"
                    }}]},
                ).execute()
                # очистка пользовательских зон
                for rng in ["C8:K39", "C45:K76"]:
                    try:
                        self.svc.spreadsheets().values().clear(
                            spreadsheetId=self.spreadsheet_id, range=f"{new_title}!{rng}", body={}
                        ).execute()
                    except Exception:
                        pass
            else:
                self._ensure_sheet(new_title)
        log.info("Rollover: проверено, добавлено: %s", to_create)

    # ---------- утилита: получить все листы в порядке слева→направо
    def list_sheet_titles_ordered(self) -> list[str]:
        """Возвращает список названий вкладок (tabs) в порядке слева→направо."""
        meta = self.svc.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        sheets = meta.get("sheets", [])
        sheets.sort(key=lambda s: s.get("properties", {}).get("index", 0))
        return [s.get("properties", {}).get("title", "") for s in sheets if s.get("properties")]

    # ---------- обеспечить 14 дней слева (слева — самая дальняя дата, справа — ближе)
    def ensure_future_days_desc(self, *, how_many: int = 14) -> tuple[list[str], list[str]]:
        meta = self.svc.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        sheets = meta.get("sheets", [])
        re_day = re.compile(r"^\d{2}-\d{2}-\d{4}$")

        day_sheets = [s for s in sheets if re_day.match(s["properties"]["title"])]
        # берем в качестве шаблона САМЫЙ левый дневной лист
        day_sheets.sort(key=lambda s: s["properties"]["index"])
        template_id = day_sheets[0]["properties"]["sheetId"] if day_sheets else None

        titles = [s["properties"]["title"] for s in sheets]
        today = datetime.now().date()
        needed = [(today + timedelta(days=i)).strftime("%d-%m-%Y") for i in range(how_many)]
        missing = [t for t in needed if t not in titles]

        created = []
        for new_title in missing:
            if template_id is None:
                self._ensure_sheet(new_title)
                created.append(new_title)
                continue
            copy_resp = self.svc.spreadsheets().sheets().copyTo(
                spreadsheetId=self.spreadsheet_id,
                sheetId=template_id,
                body={"destinationSpreadsheetId": self.spreadsheet_id},
            ).execute()
            new_id = copy_resp["sheetId"]
            # переименуем
            self.svc.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": [{"updateSheetProperties": {
                    "properties": {"sheetId": new_id, "title": new_title},
                    "fields": "title"
                }}]},
            ).execute()
            # очистим зоны и обновим шапку с датой
            for rng in ["C8:K39", "C45:K76"]:
                try:
                    self.svc.spreadsheets().values().clear(
                        spreadsheetId=self.spreadsheet_id, range=f"{new_title}!{rng}", body={}
                    ).execute()
                except Exception:
                    pass
            self._update_header_date(new_title)
            created.append(new_title)

        # переставим порядок: слева самая дальняя дата → справа ближе к текущей
        desired_order = sorted(needed, key=lambda t: datetime.strptime(t, "%d-%m-%Y"), reverse=True)
        # прогоним batchUpdate с moveSheet
        title_to_id = {}
        meta2 = self.svc.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        for s in meta2.get("sheets", []):
            title_to_id[s["properties"]["title"]] = s["properties"]["sheetId"]
        requests = []
        for idx, title in enumerate(desired_order):
            if title in title_to_id:
                requests.append({
                    "updateSheetProperties": {
                        "properties": {"sheetId": title_to_id[title], "index": idx},
                        "fields": "index"
                    }
                })
        if requests:
            self.svc.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests}
            ).execute()

        order_now = self.list_sheet_titles_ordered()
        log.info("ensure_future_days_desc: created=%s; order (left→right)=%s", created, order_now)
        return created, order_now

    # обновляет строку вида «Расписание на Пятница, 29.08.2025» (ищем в первых 10 строках)
    def _update_header_date(self, sheet_title: str):
        try:
            resp = self.svc.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{sheet_title}!A1:Z10"
            ).execute()
            vals = resp.get("values", [])
            target_row, target_col = None, None
            for r_i, row in enumerate(vals, start=1):
                for c_i, cell in enumerate(row, start=1):
                    if "Расписание на" in str(cell):
                        target_row, target_col = r_i, c_i
                        break
                if target_row:
                    break
            # составим новую строку
            dt = datetime.strptime(sheet_title, "%d-%m-%Y").date()
            ru_wdays = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
            wday = ru_wdays[dt.weekday()]
            new_text = f"Расписание на {wday}, {dt.strftime('%d.%m.%Y')}"
            if target_row:
                cell_a1 = self._a1(target_row, target_col)
                self._values_update(f"{sheet_title}!{cell_a1}", [[new_text]])
        except Exception:
            pass

    @staticmethod
    def _a1(r: int, c: int) -> str:
        # 1->A, 2->B...
        name = ""
        while c > 0:
            c, rem = divmod(c-1, 26)
            name = chr(65 + rem) + name
        return f"{name}{r}"

    # ---------- низкоуровневые ----------
    def _ensure_sheet(self, title: str, header: Optional[List[str]] = None) -> None:
        meta = self.svc.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if title not in existing:
            body = {"requests": [{"addSheet": {"properties": {"title": title}}}]}
            self.svc.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id, body=body).execute()
            if header:
                self._values_update(f"{title}!A1", [header])

    def _values_get(self, rng: str) -> List[List[Any]]:
        resp = self.svc.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=rng).execute()
        return resp.get("values", [])

    def _values_update(self, rng: str, values: List[List[Any]]) -> None:
        body = {"range": rng, "majorDimension": "ROWS", "values": values}
        self.svc.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id, range=rng, valueInputOption="USER_ENTERED", body=body
        ).execute()

    def _values_append(self, rng: str, values: List[List[Any]]) -> None:
        body = {"values": values, "majorDimension": "ROWS"}
        self.svc.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=rng,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()
