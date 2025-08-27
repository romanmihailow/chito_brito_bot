# -*- coding: utf-8 -*-
"""
Простая реализация KB: тянем Google Doc, бьём на чанки, создаём FAISS,
отвечаем через OpenAI, опираясь на найденный контекст.
Никаких упоминаний источников в ответах.
"""
from __future__ import annotations

import os
import re
import time
from typing import List, Tuple

import numpy as np
import faiss

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from openai import OpenAI

DOCS_SCOPE = ["https://www.googleapis.com/auth/documents.readonly"]

def _clean_text(t: str) -> str:
    t = t.replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> List[str]:
    text = _clean_text(text)
    if len(text) <= max_chars:
        return [text]
    chunks = []
    i = 0
    while i < len(text):
        chunk = text[i: i + max_chars]
        # мягко обрежем по границе предложения
        m = re.search(r".*[\.!\?](\s|$)", chunk, flags=re.S)
        if m and m.end() > 400:
            end = m.end()
        else:
            end = len(chunk)
        chunks.append(chunk[:end].strip())
        i += max(1, end - overlap)
    return [c for c in chunks if c]

class KnowledgeBase:
    def __init__(self, *, credentials_json_path: str, doc_id: str, openai_api_key: str):
        self.doc_id = doc_id
        self.openai_key = openai_api_key
        self._client = OpenAI(api_key=openai_api_key) if openai_api_key else None

        creds = Credentials.from_service_account_file(credentials_json_path, scopes=DOCS_SCOPE)
        self.docs = build("docs", "v1", credentials=creds, cache_discovery=False)

        self._index = None
        self._chunks: List[str] = []
        self._dim = 1536  # text-embedding-3-small
        self._last_sync = 0.0
        self._sync_and_reindex()

    def _fetch_doc_text(self) -> str:
        doc = self.docs.documents().get(documentId=self.doc_id).execute()
        body = doc.get("body", {}).get("content", [])
        parts = []
        for el in body:
            paras = el.get("paragraph", {})
            elements = paras.get("elements", [])
            for it in elements:
                text_run = it.get("textRun", {})
                content = text_run.get("content", "")
                parts.append(content)
        return _clean_text("".join(parts))

    def _embed(self, texts: List[str]) -> np.ndarray:
        if not self._client:
            raise RuntimeError("OPENAI_API_KEY не задан")
        # batched embeddings
        resp = self._client.embeddings.create(
            model="text-embedding-3-small",
            input=texts
        )
        vecs = [d.embedding for d in resp.data]
        return np.array(vecs, dtype="float32")

    def _sync_and_reindex(self):
        # не чаще раза в 3 минуты
        if time.time() - self._last_sync < 180 and self._index is not None:
            return
        text = self._fetch_doc_text()
        chunks = _chunk_text(text)
        if not chunks:
            self._index = None
            self._chunks = []
            self._last_sync = time.time()
            return
        embs = self._embed(chunks)
        index = faiss.IndexFlatIP(self._dim)
        # нормализация для cosine
        faiss.normalize_L2(embs)
        index.add(embs)
        self._index = index
        self._chunks = chunks
        self._last_sync = time.time()

    def _search(self, query: str, k: int = 5) -> List[str]:
        self._sync_and_reindex()
        if not self._index or not self._chunks:
            return []
        q = self._embed([query])
        faiss.normalize_L2(q)
        D, I = self._index.search(q, min(k, len(self._chunks)))
        idxs = I[0].tolist()
        return [self._chunks[i] for i in idxs if 0 <= i < len(self._chunks)]

    def answer(self, user_text: str) -> Tuple[str, List[str]]:
        ctx = self._search(user_text, k=5)
        if not self._client or not ctx:
            # запасной вариант — вежливо ответить
            return "Пока не могу ответить на этот вопрос. Могу помочь с записью.", []
        system = (
            "Ты вежливый ассистент салона мужской парикмахерской. "
            "Отвечай кратко и по делу, основываясь ТОЛЬКО на предоставленном контексте. "
            "Говори по-русски, в стиле администратора. Никогда не упоминай откуда ты это знаешь."
        )
        prompt = (
            "Контекст:\n"
            + "\n\n".join(ctx)
            + "\n\nВопрос клиента: " + user_text + "\n\nДай точный полезный ответ."
        )
        resp = self._client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
        )
        return (resp.choices[0].message.content.strip(), ctx)
