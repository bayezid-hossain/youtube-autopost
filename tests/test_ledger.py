import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autopost.ledger import Ledger

T = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def test_missing_file_means_empty(tmp_path):
    ledger = Ledger(tmp_path / "posted_log.json")
    assert ledger.entries == []
    assert not ledger.has("x")


def test_add_records_and_persists(tmp_path):
    path = tmp_path / "posted_log.json"
    Ledger(path).add("drive1", "yt1", T, T)

    reloaded = Ledger(path)
    assert reloaded.has("drive1")
    assert json.loads(path.read_text(encoding="utf-8")) == [
        {
            "drive_file_id": "drive1",
            "youtube_video_id": "yt1",
            "publish_at": "2026-11-19T12:00:00+00:00",
            "uploaded_at": "2026-11-19T12:00:00+00:00",
        }
    ]


def test_add_appends(tmp_path):
    path = tmp_path / "posted_log.json"
    ledger = Ledger(path)
    ledger.add("a", "1", T, T)
    ledger.add("b", "2", T, T)
    assert [e["drive_file_id"] for e in Ledger(path).entries] == ["a", "b"]


@pytest.mark.parametrize("content", ["{not json", '{"a": 1}'])
def test_corrupted_ledger_raises_clear_error(tmp_path, content):
    path = tmp_path / "posted_log.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="posted_log.json is corrupted"):
        Ledger(path)


def test_add_writes_atomically(tmp_path, monkeypatch):
    path = tmp_path / "posted_log.json"
    ledger = Ledger(path)
    ledger.add("a", "1", T, T)
    calls = []
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda s, d: (calls.append((Path(s), Path(d))), real_replace(s, d)))
    ledger.add("b", "2", T, T)
    assert calls == [(path.with_name("posted_log.json.tmp"), path)]
    assert not path.with_name("posted_log.json.tmp").exists()


def test_bom_prefixed_ledger_loads(tmp_path):
    path = tmp_path / "posted_log.json"
    path.write_text("\ufeff[]", encoding="utf-8")
    assert Ledger(path).entries == []
