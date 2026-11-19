import json
from datetime import datetime, timezone

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
