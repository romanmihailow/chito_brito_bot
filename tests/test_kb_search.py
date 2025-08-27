# -*- coding: utf-8 -*-
from src.kb_index import KBIndex

def test_kb_lazy_empty(monkeypatch, tmp_path):
    kb = KBIndex(google_doc_id="", credentials_json_path="/dev/null", openai_api_key="", data_dir=tmp_path.as_posix())
    ans, ref = kb.answer("режим работы")
    assert ans is None and ref is None
