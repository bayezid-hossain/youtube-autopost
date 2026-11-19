from unittest.mock import MagicMock

from autopost.drive import Drive, split_listing
from autopost.models import DriveFile


def f(file_id, name, created="2026-11-01T00:00:00Z"):
    return DriveFile(id=file_id, name=name, created_time=created)


def test_split_listing_separates_videos_and_sidecars():
    files = [
        f("2", "b.MP4", "2026-11-02T00:00:00Z"),
        f("1", "a.mov", "2026-11-01T00:00:00Z"),
        f("3", "a.json"),
        f("4", "a.txt"),
        f("5", "notes.pdf"),
    ]
    videos, sidecars = split_listing(files)
    assert [v.id for v in videos] == ["1", "2"]  # oldest first
    assert [s.id for s in sidecars["a"]] == ["3", "4"]
    assert "notes" not in sidecars


def test_list_folder_follows_pages():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "1", "name": "a.mp4", "createdTime": "t1"}], "nextPageToken": "p2"},
        {"files": [{"id": "2", "name": "b.mp4", "createdTime": "t2"}]},
    ]
    files = Drive(service).list_folder("folder")
    assert files == [f("1", "a.mp4", "t1"), f("2", "b.mp4", "t2")]
    first_call = service.files.return_value.list.call_args_list[0].kwargs
    assert "'folder' in parents" in first_call["q"]
    assert "trashed = false" in first_call["q"]


def test_read_text_decodes_utf8_with_bom():
    service = MagicMock()
    service.files.return_value.get_media.return_value.execute.return_value = (
        "﻿Title ✓".encode("utf-8")
    )
    assert Drive(service).read_text("id") == "Title ✓"


def test_move_swaps_parents():
    service = MagicMock()
    Drive(service).move("id", "from", "to")
    kwargs = service.files.return_value.update.call_args.kwargs
    assert kwargs["fileId"] == "id"
    assert kwargs["addParents"] == "to"
    assert kwargs["removeParents"] == "from"


def test_download_writes_all_chunks(tmp_path, monkeypatch):
    class FakeDownloader:
        def __init__(self, fh, request, chunksize):
            self.fh = fh
            self.calls = 0

        def next_chunk(self, num_retries=0):
            self.calls += 1
            self.fh.write(b"ab")
            return None, self.calls >= 2

    monkeypatch.setattr("autopost.drive.MediaIoBaseDownload", FakeDownloader)
    dest = tmp_path / "video.mp4"
    Drive(MagicMock()).download("id", dest)
    assert dest.read_bytes() == b"abab"
