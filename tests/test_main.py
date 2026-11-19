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
