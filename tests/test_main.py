from datetime import datetime, timezone
from pathlib import Path

import pytest

from autopost.ledger import Ledger
from autopost.main import RunResult, format_summary, run
from autopost.models import DriveFile, Job
from autopost.youtube import QuotaExceeded

NOW = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)  # 06:00 in Asia/Dhaka


def f(file_id, name, created="2026-11-01T00:00:00Z"):
    return DriveFile(id=file_id, name=name, created_time=created)


class FakeDrive:
    def __init__(self, folders, texts=None, fail_download=(), fail_move=False):
        self.folders = folders
        self.texts = texts or {}
        self.fail_download = set(fail_download)
        self.fail_move = fail_move
        self.downloads = []
        self.moves = []

    def list_folder(self, folder_id):
        return list(self.folders.get(folder_id, []))

    def download(self, file_id, dest):
        if file_id in self.fail_download:
            raise OSError("download broke")
        Path(dest).write_bytes(b"video")
        self.downloads.append(file_id)

    def read_text(self, file_id):
        return self.texts[file_id]

    def move(self, file_id, from_folder, to_folder):
        if self.fail_move:
            raise OSError("move broke")
        self.moves.append((file_id, from_folder, to_folder))


class FakeUploader:
    def __init__(self, quota_after=None):
        self.bodies = []
        self.quota_after = quota_after

    def __call__(self, path, body):
        if self.quota_after is not None and len(self.bodies) >= self.quota_after:
            raise QuotaExceeded("quota")
        assert Path(path).exists()
        self.bodies.append(body)
        return f"yt{len(self.bodies)}"


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "posted_log.json")


@pytest.fixture
def workdir(tmp_path):
    path = tmp_path / "work"
    path.mkdir()
    return path


def go(cfg, drive, uploader, ledger, workdir, dry_run=False):
    return run(cfg, drive, uploader, ledger, None, NOW, dry_run, workdir)


def test_uploads_planned_files_and_moves_them(cfg, ledger, workdir):
    drive = FakeDrive(
        {"v": [f("v1", "cake.mp4")], "s": [f("s1", "tip.mp4"), f("s1j", "tip.json")]},
        texts={"s1j": '{"title": "Quick tip"}'},
    )
    uploader = FakeUploader()
    result = go(cfg, drive, uploader, ledger, workdir)

    assert [(job.file.id, vid) for job, vid in result.uploaded] == [("s1", "yt1"), ("v1", "yt2")]
    assert uploader.bodies[0]["snippet"]["title"] == "Quick tip"
    assert uploader.bodies[1]["snippet"]["title"] == "cake"
    assert ledger.has("s1") and ledger.has("v1")
    assert drive.moves == [("s1", "s", "p"), ("s1j", "s", "p"), ("v1", "v", "p")]
    assert result.queue_left == {"video": 0, "short": 0}
    assert result.failed == []
    assert list(workdir.iterdir()) == []  # temp files deleted


def test_already_posted_file_is_moved_not_reuploaded(cfg, ledger, workdir):
    ledger.add("v1", "old", NOW, NOW)
    drive = FakeDrive({"v": [f("v1", "cake.mp4")]})
    uploader = FakeUploader()
    result = go(cfg, drive, uploader, ledger, workdir)

    assert result.uploaded == []
    assert uploader.bodies == []
    assert drive.moves == [("v1", "v", "p")]


def test_download_failure_skips_only_that_file(cfg, ledger, workdir):
    drive = FakeDrive(
        {"s": [f("s1", "a.mp4", "t1"), f("s2", "b.mp4", "t2")]},
        fail_download={"s1"},
    )
    result = go(cfg, drive, FakeUploader(), ledger, workdir)

    assert [job.file.id for job, _ in result.failed] == ["s1"]
    assert [job.file.id for job, _ in result.uploaded] == ["s2"]
    assert not ledger.has("s1")
    assert ("s1", "s", "p") not in drive.moves


def test_quota_stops_run(cfg, ledger, workdir):
    drive = FakeDrive({"s": [f("s1", "a.mp4", "t1"), f("s2", "b.mp4", "t2")]})
    result = go(cfg, drive, FakeUploader(quota_after=1), ledger, workdir)

    assert [job.file.id for job, _ in result.uploaded] == ["s1"]
    assert result.quota_hit is True
    assert result.failed == []
    assert not ledger.has("s2")
    assert result.queue_left == {"video": 0, "short": 1}


def test_dry_run_changes_nothing(cfg, ledger, workdir):
    drive = FakeDrive({"v": [f("v1", "cake.mp4")], "s": [f("s1", "a.mp4")]})
    uploader = FakeUploader()
    result = go(cfg, drive, uploader, ledger, workdir, dry_run=True)

    assert [job.file.id for job in result.planned] == ["s1", "v1"]
    assert result.uploaded == []
    assert uploader.bodies == []
    assert drive.downloads == [] and drive.moves == []
    assert not ledger.path.exists()


def test_move_failure_after_upload_keeps_ledger(cfg, ledger, workdir):
    drive = FakeDrive({"v": [f("v1", "cake.mp4")]}, fail_move=True)
    result = go(cfg, drive, FakeUploader(), ledger, workdir)

    assert [job.file.id for job, _ in result.uploaded] == ["v1"]
    assert result.failed == []
    assert ledger.has("v1")


def job(kind, file_id, name):
    return Job(kind=kind, file=f(file_id, name), publish_at=datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc))


def test_format_summary_lists_outcomes():
    result = RunResult(
        planned=[job("short", "s1", "a.mp4"), job("video", "v1", "b.mp4")],
        uploaded=[(job("short", "s1", "a.mp4"), "abc")],
        failed=[(job("video", "v1", "b.mp4"), "download broke")],
        quota_hit=True,
        queue_left={"video": 3, "short": 0},
    )
    text = format_summary(result, dry_run=False)
    assert text.splitlines()[0] == "autopost run: 1 uploaded, 1 failed, 2 planned"
    assert "- uploaded short a.mp4 -> https://youtu.be/abc" in text
    assert "- FAILED video b.mp4: download broke" in text
    assert "- stopped: YouTube daily quota reached" in text
    assert "Queue left: 3 videos, 0 shorts" in text
    assert "Queue empty" not in text


def test_format_summary_dry_run_and_empty_queue():
    result = RunResult(planned=[job("video", "v1", "b.mp4")], queue_left={"video": 0, "short": 0})
    text = format_summary(result, dry_run=True)
    assert text.splitlines()[0].startswith("autopost dry run:")
    assert "- would upload video b.mp4 at 2026-11-19 12:00 UTC" in text
    assert "Queue empty: add more files to Drive." in text


def test_cli_help_exits_zero(capsys):
    from autopost.main import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "--dry-run" in capsys.readouterr().out


def test_ledger_write_failure_stops_run_and_keeps_file_in_place(cfg, ledger, workdir, monkeypatch, caplog):
    def broken_add(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ledger, "add", broken_add)
    drive = FakeDrive({"s": [f("s1", "a.mp4", "t1"), f("s2", "b.mp4", "t2")]})
    uploader = FakeUploader()
    with caplog.at_level("ERROR", logger="autopost"):
        result = go(cfg, drive, uploader, ledger, workdir)

    assert len(result.failed) == 1
    job_failed, message = result.failed[0]
    assert job_failed.file.id == "s1"
    assert "yt1" in message and "disk full" in message
    assert result.uploaded == []
    assert len(uploader.bodies) == 1  # later jobs not uploaded
    assert drive.moves == []
    assert "yt1" in caplog.text and "a.mp4" in caplog.text


def test_main_bad_config_returns_1_without_traceback(tmp_path, monkeypatch, raw_config):
    import yaml

    from autopost.main import main

    raw_config["timezone"] = "Mars/Olympus"
    bad = tmp_path / "config.yaml"
    bad.write_text(yaml.safe_dump(raw_config), encoding="utf-8")
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.setenv(name, "dummy")

    assert main(["--config", str(bad), "--ledger", str(tmp_path / "log.json")]) == 1


def test_main_placeholder_drive_ids_return_1(tmp_path, monkeypatch, raw_config, caplog):
    import yaml

    from autopost.main import main

    raw_config["drive"]["posted_folder_id"] = "REPLACE_WITH_POSTED_FOLDER_ID"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw_config), encoding="utf-8")
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.setenv(name, "dummy")

    with caplog.at_level("ERROR", logger="autopost"):
        assert main(["--config", str(path), "--ledger", str(tmp_path / "log.json")]) == 1
    assert "placeholder Drive folder IDs" in caplog.text


def test_main_http_error_returns_1(tmp_path, monkeypatch, raw_config, caplog):
    from unittest.mock import MagicMock

    import httplib2
    import yaml
    from googleapiclient.errors import HttpError

    import autopost.main as main_module

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw_config), encoding="utf-8")
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.setenv(name, "dummy")

    def boom(*args, **kwargs):
        raise HttpError(httplib2.Response({"status": 404}), b"not found")

    monkeypatch.setattr(main_module, "build", lambda *a, **k: MagicMock())
    monkeypatch.setattr(main_module, "run", boom)

    with caplog.at_level("ERROR", logger="autopost"):
        assert main_module.main(["--config", str(path), "--ledger", str(tmp_path / "log.json")]) == 1
    assert "Google API error" in caplog.text


def test_single_read_only_folder_with_hashtags(cfg, ledger, workdir):
    import dataclasses

    single = dataclasses.replace(
        cfg,
        short_slots=(),
        queue_shorts_folder_id=None,
        posted_folder_id=None,
        hashtags_file="Hash_Tag.txt",
    )
    drive = FakeDrive(
        {"v": [f("v1", "combo.mp4"), f("h", "Hash_Tag.txt")]},
        texts={"h": "\\#gaming\n\\#mk11\nSome title\n"},
    )
    uploader = FakeUploader()
    result = go(single, drive, uploader, ledger, workdir)

    assert [job.file.id for job, _ in result.uploaded] == ["v1"]
    body = uploader.bodies[0]
    assert body["snippet"]["description"].endswith("#gaming #mk11")
    assert "gaming" in body["snippet"]["tags"] and "mk11" in body["snippet"]["tags"]
    assert drive.moves == []  # no posted folder: nothing is moved
    assert ledger.has("v1")
    assert result.queue_left == {"video": 0, "short": 0}


def test_missing_hashtags_file_still_uploads(cfg, ledger, workdir):
    import dataclasses

    single = dataclasses.replace(cfg, short_slots=(), queue_shorts_folder_id=None, hashtags_file="Hash_Tag.txt")
    drive = FakeDrive({"v": [f("v1", "combo.mp4")]})
    result = go(single, drive, FakeUploader(), ledger, workdir)
    assert [job.file.id for job, _ in result.uploaded] == ["v1"]


def test_format_queue_lists_remaining_files_with_expected_publish_times(cfg):
    import dataclasses as dc
    from datetime import datetime, time

    from autopost.main import RunResult, format_queue
    from autopost.models import DriveFile

    cfg = dc.replace(cfg, video_slots=(time(9, 0), time(18, 0)), short_slots=(), daily_cap=2)
    files = [
        DriveFile("a", "first.mp4", "2026-11-18T14:52:36Z"),
        DriveFile("b", "sec|ond.mp4", "2026-11-18T14:52:40Z"),
        DriveFile("c", "third.mp4", "2026-11-18T14:52:44Z"),
    ]
    result = RunResult(remaining={"video": files, "short": []})
    early = datetime(2026, 11, 26, 6, 0, tzinfo=cfg.timezone)  # before the morning run: today counts
    text = format_queue(result, cfg, early, dry_run=True)
    rows = [line for line in text.splitlines() if line.startswith("| ") and line[2].isdigit()]
    assert len(rows) == 3
    assert "first.mp4" in rows[0] and "2026-11-26 09:00" in rows[0]
    assert "sec\|ond.mp4" in rows[1] and "2026-11-26 18:00" in rows[1]
    assert "third.mp4" in rows[2] and "2026-11-27 09:00" in rows[2]

    afternoon = datetime(2026, 11, 26, 17, 0, tzinfo=cfg.timezone)  # no run left today: starts tomorrow
    text = format_queue(result, cfg, afternoon, dry_run=True)
    assert text.index("first.mp4") < text.index("2026-11-27 09:00")
    assert "2026-11-26" not in text.split("|---|")[1]


def test_format_queue_after_real_run_starts_tomorrow(cfg):
    import dataclasses as dc
    from datetime import datetime, time, timezone

    from autopost.main import RunResult, format_queue
    from autopost.models import DriveFile, Job

    cfg = dc.replace(cfg, video_slots=(time(18, 0),), short_slots=(), daily_cap=1)
    done = DriveFile("x", "done.mp4", "t")
    nxt = DriveFile("a", "next.mp4", "2026-11-18T14:52:36Z")
    planned = [Job("video", done, datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc))]
    result = RunResult(planned=planned, uploaded=[(planned[0], "vid")], remaining={"video": [nxt], "short": []})
    now = datetime(2026, 11, 26, 6, 7, tzinfo=cfg.timezone)
    text = format_queue(result, cfg, now, dry_run=False)
    assert "2026-11-27 18:00" in text and "done.mp4" not in text


def test_format_queue_empty(cfg):
    from datetime import datetime, timezone

    from autopost.main import RunResult, format_queue

    text = format_queue(RunResult(remaining={"video": [], "short": []}), cfg, datetime.now(timezone.utc), True)
    assert "Queue empty" in text
