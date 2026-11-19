# Drive → YouTube Autopost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python job, run once a day by GitHub Actions, that takes the next videos and Shorts from Google Drive queue folders and uploads them to YouTube against fixed daily time slots, using only free services.

**Architecture:** Small single-purpose modules in the `autopost/` package: config, scheduler, ledger, drive, metadata, gemini, youtube, auth, notify. `main.run()` wires them together through injected dependencies, so the whole pipeline is unit-tested with fakes. Video bytes stream Drive → runner temp disk → YouTube resumable upload; no LLM ever touches them. Gemini only writes text metadata when a sidecar file is missing.

**Tech Stack:** Python 3.12, google-api-python-client, google-auth, google-auth-oauthlib, google-genai, PyYAML, tzdata, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-19-drive-to-youtube-autopost-design.md`

**Spec deviation (deliberate):** GitHub Pages on a *private* repo needs a paid GitHub plan. The privacy policy and terms pages therefore live in a separate tiny **public** repo with GitHub Pages enabled (free). Task 15 creates the content; the README explains where to put it.

---

## File structure

```
autopost/
  __init__.py        package marker
  __main__.py        `python -m autopost` entry → main.main()
  models.py          DriveFile, Metadata, Job dataclasses (shared types, no logic)
  config.py          load + validate config.yaml → Config
  scheduler.py       plan_day(): today's slots → Jobs
  ledger.py          posted_log.json read/append, duplicate check
  drive.py           split_listing() + Drive wrapper (list, download, read_text, move)
  metadata.py        sidecar parsing, fallback, YouTube limits → Metadata
  gemini.py          make_gemini(): Gemini client → metadata generator callable
  youtube.py         build_body(), upload(), QuotaExceeded
  auth.py            SCOPES, credentials_from_env()
  notify.py          send_telegram(), write_step_summary()
  main.py            run(), format_summary(), main() CLI
auth_setup.py        local one-time OAuth flow → prints refresh token
config.yaml          user settings
posted_log.json      ledger (starts as [])
requirements.txt
pyproject.toml       pytest config only
.gitignore
.github/workflows/autopost.yml
tests/
  conftest.py        raw_config + cfg fixtures
  test_config.py  test_scheduler.py  test_ledger.py  test_drive.py
  test_metadata.py  test_gemini.py  test_youtube.py  test_auth.py
  test_notify.py  test_main.py
docs/
  README section lives in README.md (root)
  policy/privacy-policy.md  policy/terms.md  audit-notes.md
README.md
```

All commands below run from the repo root `c:\Users\amiba\Projects\youtube autopost` in PowerShell with the venv active.

---

### Task 1: Project scaffold

**Files:**
- Create: `.gitignore`, `requirements.txt`, `pyproject.toml`, `autopost/__init__.py`, `posted_log.json`

- [ ] **Step 1: Create `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
client_secret*.json
token*.json
.env
```

- [ ] **Step 2: Create `requirements.txt`**

```text
google-api-python-client>=2.150
google-auth>=2.35
google-auth-oauthlib>=1.2
google-genai>=1.0
PyYAML>=6.0
tzdata>=2024.1
pytest>=8.0
```

`tzdata` is required on Windows, where `zoneinfo` has no system timezone database.

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 4: Create `autopost/__init__.py`**

```python
"""Upload queued Google Drive videos to YouTube on a daily schedule."""
```

- [ ] **Step 5: Create `posted_log.json`**

```json
[]
```

- [ ] **Step 6: Create venv and install**

Run:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
```
Expected: install succeeds; pytest prints `no tests ran` (exit code 5 is fine here).

- [ ] **Step 7: Commit**

```powershell
git add .gitignore requirements.txt pyproject.toml autopost/__init__.py posted_log.json
git commit -m "chore: scaffold autopost package"
```

---

### Task 2: Shared models

**Files:**
- Create: `autopost/models.py`

No tests: pure data containers, exercised by every later test.

- [ ] **Step 1: Create `autopost/models.py`**

```python
"""Plain data types shared across modules."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    created_time: str  # RFC 3339 string from Drive; sorts chronologically as text


@dataclass(frozen=True)
class Metadata:
    title: str
    description: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Job:
    kind: str  # "video" or "short"
    file: DriveFile
    publish_at: datetime  # timezone-aware, UTC
```

- [ ] **Step 2: Commit**

```powershell
git add autopost/models.py
git commit -m "feat: add shared data models"
```

---

### Task 3: Config loading and validation

**Files:**
- Create: `autopost/config.py`, `tests/conftest.py`, `tests/test_config.py`

- [ ] **Step 1: Create `tests/conftest.py`**

```python
import copy

import pytest

from autopost.config import parse_config

BASE_RAW = {
    "timezone": "Asia/Dhaka",
    "publish_mode": "private",
    "daily_cap": 6,
    "slots": {"videos": ["18:00"], "shorts": ["13:00", "10:00"]},
    "drive": {
        "queue_videos_folder_id": "v",
        "queue_shorts_folder_id": "s",
        "posted_folder_id": "p",
    },
    "defaults": {
        "description": "Channel about home cooking.",
        "tags": ["cooking", "recipes"],
        "category_id": "26",
        "made_for_kids": False,
    },
    "gemini_model": "gemini-flash-latest",
}


@pytest.fixture
def raw_config():
    return copy.deepcopy(BASE_RAW)


@pytest.fixture
def cfg(raw_config):
    return parse_config(raw_config)
```

- [ ] **Step 2: Write failing tests `tests/test_config.py`**

```python
from datetime import time

import pytest

from autopost.config import ConfigError, load_config, parse_config


def test_valid_config_parses(raw_config):
    cfg = parse_config(raw_config)
    assert cfg.timezone.key == "Asia/Dhaka"
    assert cfg.publish_mode == "private"
    assert cfg.daily_cap == 6
    assert cfg.video_slots == (time(18, 0),)
    assert cfg.short_slots == (time(10, 0), time(13, 0))  # sorted
    assert cfg.queue_videos_folder_id == "v"
    assert cfg.queue_shorts_folder_id == "s"
    assert cfg.posted_folder_id == "p"
    assert cfg.default_tags == ("cooking", "recipes")
    assert cfg.category_id == "26"
    assert cfg.made_for_kids is False
    assert cfg.gemini_model == "gemini-flash-latest"


def test_defaults_when_optional_keys_missing(raw_config):
    del raw_config["publish_mode"], raw_config["daily_cap"]
    del raw_config["defaults"], raw_config["gemini_model"]
    cfg = parse_config(raw_config)
    assert cfg.publish_mode == "private"
    assert cfg.daily_cap == 6
    assert cfg.default_description == ""
    assert cfg.default_tags == ()
    assert cfg.category_id == "22"
    assert cfg.gemini_model == "gemini-flash-latest"


@pytest.mark.parametrize("tz", [None, "", "Mars/Olympus"])
def test_bad_timezone_rejected(raw_config, tz):
    raw_config["timezone"] = tz
    with pytest.raises(ConfigError, match="timezone"):
        parse_config(raw_config)


def test_bad_publish_mode_rejected(raw_config):
    raw_config["publish_mode"] = "public"
    with pytest.raises(ConfigError, match="publish_mode"):
        parse_config(raw_config)


@pytest.mark.parametrize("cap", [0, 7, "6", True])
def test_bad_daily_cap_rejected(raw_config, cap):
    raw_config["daily_cap"] = cap
    with pytest.raises(ConfigError, match="daily_cap"):
        parse_config(raw_config)


def test_more_slots_than_cap_rejected(raw_config):
    raw_config["daily_cap"] = 2
    with pytest.raises(ConfigError, match="daily_cap is 2"):
        parse_config(raw_config)


def test_no_slots_rejected(raw_config):
    raw_config["slots"] = {}
    with pytest.raises(ConfigError, match="at least one slot"):
        parse_config(raw_config)


@pytest.mark.parametrize("slot", ["25:00", "6:00", "18.00", 1080])
def test_malformed_slot_rejected(raw_config, slot):
    raw_config["slots"]["videos"] = [slot]
    with pytest.raises(ConfigError, match="HH:MM"):
        parse_config(raw_config)


@pytest.mark.parametrize("slot", ["06:30", "05:00"])
def test_slot_too_early_rejected(raw_config, slot):
    raw_config["slots"]["videos"] = [slot]
    with pytest.raises(ConfigError, match="later than 06:30"):
        parse_config(raw_config)


def test_missing_drive_folder_rejected(raw_config):
    del raw_config["drive"]["posted_folder_id"]
    with pytest.raises(ConfigError, match="drive.posted_folder_id"):
        parse_config(raw_config)


def test_load_config_reads_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        'timezone: Asia/Dhaka\n'
        'slots:\n  videos: ["18:00"]\n'
        'drive:\n  queue_videos_folder_id: v\n  queue_shorts_folder_id: s\n  posted_folder_id: p\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.video_slots == (time(18, 0),)


def test_load_config_rejects_non_mapping(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'autopost.config'`.

- [ ] **Step 4: Implement `autopost/config.py`**

```python
"""Load and validate config.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

MAX_DAILY_UPLOADS = 6  # YouTube free quota: 10,000 units/day, ~1,600 per upload
EARLIEST_SLOT = time(6, 30)  # daily run starts 06:00 local and needs lead time
PUBLISH_MODES = ("private", "scheduled")
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DRIVE_KEYS = ("queue_videos_folder_id", "queue_shorts_folder_id", "posted_folder_id")


class ConfigError(ValueError):
    """config.yaml is missing a value or has an invalid one."""


@dataclass(frozen=True)
class Config:
    timezone: ZoneInfo
    publish_mode: str
    daily_cap: int
    video_slots: tuple[time, ...]
    short_slots: tuple[time, ...]
    queue_videos_folder_id: str
    queue_shorts_folder_id: str
    posted_folder_id: str
    default_description: str
    default_tags: tuple[str, ...]
    category_id: str
    made_for_kids: bool
    gemini_model: str


def _parse_timezone(value) -> ZoneInfo:
    if not isinstance(value, str) or not value:
        raise ConfigError("timezone is required, e.g. 'Asia/Dhaka'")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"unknown timezone: {value!r}") from exc


def _parse_slot(value) -> time:
    match = _HHMM.match(value) if isinstance(value, str) else None
    if not match:
        raise ConfigError(f'slot must be HH:MM in quotes, e.g. "18:00"; got {value!r}')
    slot = time(int(match.group(1)), int(match.group(2)))
    if slot <= EARLIEST_SLOT:
        raise ConfigError(f"slot {value} must be later than 06:30 (daily run starts 06:00)")
    return slot


def parse_config(raw: dict) -> Config:
    tz = _parse_timezone(raw.get("timezone"))

    mode = raw.get("publish_mode", "private")
    if mode not in PUBLISH_MODES:
        raise ConfigError(f"publish_mode must be one of {PUBLISH_MODES}, got {mode!r}")

    cap = raw.get("daily_cap", MAX_DAILY_UPLOADS)
    if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= MAX_DAILY_UPLOADS:
        raise ConfigError(f"daily_cap must be an integer 1..{MAX_DAILY_UPLOADS}, got {cap!r}")

    slots = raw.get("slots") or {}
    video_slots = tuple(sorted(_parse_slot(s) for s in slots.get("videos") or []))
    short_slots = tuple(sorted(_parse_slot(s) for s in slots.get("shorts") or []))
    total = len(video_slots) + len(short_slots)
    if total == 0:
        raise ConfigError("at least one slot is required under slots.videos or slots.shorts")
    if total > cap:
        raise ConfigError(f"{total} slots configured but daily_cap is {cap}")

    drive = raw.get("drive") or {}
    for key in _DRIVE_KEYS:
        if not isinstance(drive.get(key), str) or not drive[key]:
            raise ConfigError(f"drive.{key} is required")

    defaults = raw.get("defaults") or {}
    return Config(
        timezone=tz,
        publish_mode=mode,
        daily_cap=cap,
        video_slots=video_slots,
        short_slots=short_slots,
        queue_videos_folder_id=drive["queue_videos_folder_id"],
        queue_shorts_folder_id=drive["queue_shorts_folder_id"],
        posted_folder_id=drive["posted_folder_id"],
        default_description=str(defaults.get("description", "")),
        default_tags=tuple(str(t) for t in defaults.get("tags") or []),
        category_id=str(defaults.get("category_id", "22")),
        made_for_kids=bool(defaults.get("made_for_kids", False)),
        gemini_model=str(raw.get("gemini_model", "gemini-flash-latest")),
    )


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml must be a mapping of keys to values")
    return parse_config(raw)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```powershell
git add autopost/config.py tests/conftest.py tests/test_config.py
git commit -m "feat: load and validate config.yaml"
```

---

### Task 4: Slot scheduler

**Files:**
- Create: `autopost/scheduler.py`, `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests `tests/test_scheduler.py`**

```python
import dataclasses
from datetime import date, datetime, timezone

from autopost.models import DriveFile
from autopost.scheduler import plan_day

TODAY = date(2026, 11, 19)


def f(file_id):
    return DriveFile(id=file_id, name=f"{file_id}.mp4", created_time="2026-11-01T00:00:00Z")


def utc(h, m=0):
    return datetime(2026, 11, 19, h, m, tzinfo=timezone.utc)


def test_pairs_slots_with_queue_heads_in_time_order(cfg):
    # Asia/Dhaka is UTC+6: shorts 10:00/13:00 → 04:00/07:00 UTC, video 18:00 → 12:00 UTC
    jobs = plan_day(TODAY, utc(0), cfg, [f("v1"), f("v2")], [f("s1"), f("s2"), f("s3")])
    assert [(j.kind, j.file.id, j.publish_at) for j in jobs] == [
        ("short", "s1", utc(4)),
        ("short", "s2", utc(7)),
        ("video", "v1", utc(12)),
    ]


def test_past_slots_are_dropped(cfg):
    jobs = plan_day(TODAY, utc(8), cfg, [f("v1")], [f("s1")])  # 14:00 Dhaka
    assert [j.file.id for j in jobs] == ["v1"]


def test_empty_queue_skips_its_slots(cfg):
    jobs = plan_day(TODAY, utc(0), cfg, [f("v1")], [])
    assert [j.file.id for j in jobs] == ["v1"]


def test_daily_cap_limits_jobs(cfg):
    capped = dataclasses.replace(cfg, daily_cap=2)
    jobs = plan_day(TODAY, utc(0), capped, [f("v1")], [f("s1"), f("s2")])
    assert [j.file.id for j in jobs] == ["s1", "s2"]


def test_publish_at_is_utc(cfg):
    jobs = plan_day(TODAY, utc(0), cfg, [f("v1")], [])
    assert jobs[0].publish_at.tzinfo == timezone.utc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: `ModuleNotFoundError: No module named 'autopost.scheduler'`.

- [ ] **Step 3: Implement `autopost/scheduler.py`**

```python
"""Map today's time slots onto the next files in each queue."""
from __future__ import annotations

from datetime import date, datetime, timezone

from autopost.config import Config
from autopost.models import DriveFile, Job


def plan_day(
    today: date,
    now: datetime,
    cfg: Config,
    videos: list[DriveFile],
    shorts: list[DriveFile],
) -> list[Job]:
    """Return today's jobs in slot order. Past slots and empty queues are skipped."""
    slots = [(datetime.combine(today, t, tzinfo=cfg.timezone), "video") for t in cfg.video_slots]
    slots += [(datetime.combine(today, t, tzinfo=cfg.timezone), "short") for t in cfg.short_slots]
    slots.sort(key=lambda slot: (slot[0], slot[1]))

    queues = {"video": iter(videos), "short": iter(shorts)}
    jobs: list[Job] = []
    for when, kind in slots:
        if len(jobs) >= cfg.daily_cap:
            break
        if when <= now:
            continue
        next_file = next(queues[kind], None)
        if next_file is None:
            continue
        jobs.append(Job(kind=kind, file=next_file, publish_at=when.astimezone(timezone.utc)))
    return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add autopost/scheduler.py tests/test_scheduler.py
git commit -m "feat: plan daily upload slots"
```

---

### Task 5: Ledger

**Files:**
- Create: `autopost/ledger.py`, `tests/test_ledger.py`

- [ ] **Step 1: Write failing tests `tests/test_ledger.py`**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: `ModuleNotFoundError: No module named 'autopost.ledger'`.

- [ ] **Step 3: Implement `autopost/ledger.py`**

```python
"""posted_log.json: record of every successful upload, used to prevent duplicates."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            self.entries: list[dict] = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.entries = []
        self._ids = {entry["drive_file_id"] for entry in self.entries}

    def has(self, drive_file_id: str) -> bool:
        return drive_file_id in self._ids

    def add(
        self,
        drive_file_id: str,
        youtube_video_id: str,
        publish_at: datetime,
        uploaded_at: datetime,
    ) -> None:
        """Append one entry and write the file immediately, so a later crash keeps it."""
        self.entries.append(
            {
                "drive_file_id": drive_file_id,
                "youtube_video_id": youtube_video_id,
                "publish_at": publish_at.isoformat(),
                "uploaded_at": uploaded_at.isoformat(),
            }
        )
        self._ids.add(drive_file_id)
        self.path.write_text(json.dumps(self.entries, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add autopost/ledger.py tests/test_ledger.py
git commit -m "feat: add upload ledger"
```

---

### Task 6: Drive wrapper

**Files:**
- Create: `autopost/drive.py`, `tests/test_drive.py`

- [ ] **Step 1: Write failing tests `tests/test_drive.py`**

```python
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
        "\ufeffTitle ✓".encode("utf-8")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_drive.py -v`
Expected: `ModuleNotFoundError: No module named 'autopost.drive'`.

- [ ] **Step 3: Implement `autopost/drive.py`**

```python
"""Google Drive access: list queue folders, stream downloads, move files."""
from __future__ import annotations

import os
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload

from autopost.models import DriveFile

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"})
SIDECAR_EXTENSIONS = frozenset({".json", ".txt"})
DOWNLOAD_CHUNK = 50 * 1024 * 1024
RETRIES = 3  # googleapiclient retries with exponential backoff


def split_listing(
    files: list[DriveFile],
) -> tuple[list[DriveFile], dict[str, list[DriveFile]]]:
    """Return (videos oldest first, sidecars grouped by file stem). Other files are ignored."""
    videos: list[DriveFile] = []
    sidecars: dict[str, list[DriveFile]] = {}
    for file in files:
        stem, ext = os.path.splitext(file.name)
        ext = ext.lower()
        if ext in VIDEO_EXTENSIONS:
            videos.append(file)
        elif ext in SIDECAR_EXTENSIONS:
            sidecars.setdefault(stem, []).append(file)
    videos.sort(key=lambda v: (v.created_time, v.name))
    return videos, sidecars


class Drive:
    def __init__(self, service):
        self._service = service

    def list_folder(self, folder_id: str) -> list[DriveFile]:
        files: list[DriveFile] = []
        page_token = None
        while True:
            response = (
                self._service.files()
                .list(
                    q=(
                        f"'{folder_id}' in parents and trashed = false"
                        " and mimeType != 'application/vnd.google-apps.folder'"
                    ),
                    fields="nextPageToken, files(id, name, createdTime)",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute(num_retries=RETRIES)
            )
            files.extend(
                DriveFile(id=item["id"], name=item["name"], created_time=item["createdTime"])
                for item in response.get("files", [])
            )
            page_token = response.get("nextPageToken")
            if not page_token:
                return files

    def download(self, file_id: str, dest: Path) -> None:
        request = self._service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with open(dest, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=DOWNLOAD_CHUNK)
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=RETRIES)

    def read_text(self, file_id: str) -> str:
        data = (
            self._service.files()
            .get_media(fileId=file_id, supportsAllDrives=True)
            .execute(num_retries=RETRIES)
        )
        return data.decode("utf-8-sig")

    def move(self, file_id: str, from_folder_id: str, to_folder_id: str) -> None:
        self._service.files().update(
            fileId=file_id,
            addParents=to_folder_id,
            removeParents=from_folder_id,
            fields="id",
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_drive.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add autopost/drive.py tests/test_drive.py
git commit -m "feat: add Google Drive wrapper"
```

---

### Task 7: Metadata (sidecar → generator → fallback)

**Files:**
- Create: `autopost/metadata.py`, `tests/test_metadata.py`

- [ ] **Step 1: Write failing tests `tests/test_metadata.py`**

```python
import pytest

from autopost.metadata import (
    build_metadata,
    clean_title,
    finalize,
    parse_sidecar,
    pick_sidecar,
)
from autopost.models import DriveFile


def f(name):
    return DriveFile(id=name, name=name, created_time="t")


# --- parse_sidecar ---

def test_json_sidecar_full():
    text = '{"title": " Cake ", "description": "Easy cake", "tags": ["cake", " ", 3]}'
    assert parse_sidecar("a.json", text) == {
        "title": "Cake",
        "description": "Easy cake",
        "tags": ["cake"],
    }


def test_json_sidecar_partial():
    assert parse_sidecar("a.json", '{"title": "Cake"}') == {"title": "Cake"}


@pytest.mark.parametrize("text", ["not json", "[1, 2]"])
def test_json_sidecar_malformed_raises(text):
    with pytest.raises(ValueError):
        parse_sidecar("a.json", text)


def test_txt_sidecar_title_and_description():
    assert parse_sidecar("a.txt", "Cake\nLine one\nLine two\n") == {
        "title": "Cake",
        "description": "Line one\nLine two",
    }


def test_txt_sidecar_title_only():
    assert parse_sidecar("a.txt", "Cake\n") == {"title": "Cake"}


def test_txt_sidecar_empty():
    assert parse_sidecar("a.txt", "  \n") == {}


# --- pick_sidecar / clean_title ---

def test_pick_sidecar_prefers_json():
    assert pick_sidecar([f("a.txt"), f("a.json")]).name == "a.json"
    assert pick_sidecar([f("a.txt")]).name == "a.txt"
    assert pick_sidecar([]) is None


def test_clean_title():
    assert clean_title("my_best-cake__recipe.v2") == "my best cake recipe v2"


# --- finalize ---

def test_finalize_strips_angle_brackets_and_truncates_title():
    meta = finalize({"title": "<b>" + "x" * 200, "description": "a<b>c", "tags": []}, "video")
    assert meta.title == "b" + "x" * 99
    assert meta.description == "abc"


def test_finalize_adds_shorts_tag_only_to_shorts():
    assert finalize({"title": "t", "description": "d", "tags": []}, "short").description == "d\n\n#Shorts"
    assert finalize({"title": "t", "description": "d #shorts", "tags": []}, "short").description == "d #shorts"
    assert finalize({"title": "t", "description": "d", "tags": []}, "video").description == "d"


def test_finalize_keeps_shorts_tag_when_description_too_long():
    meta = finalize({"title": "t", "description": "x" * 6000, "tags": []}, "short")
    assert len(meta.description) <= 5000
    assert meta.description.endswith("#Shorts")


def test_finalize_fits_tags_into_500_chars():
    tags = ["a" * 100] * 10  # duplicates removed → one tag
    assert finalize({"title": "t", "description": "", "tags": tags}, "video").tags == ("a" * 100,)
    many = [f"tag{i:03d}" + "x" * 40 for i in range(20)]  # 46 chars each
    kept = finalize({"title": "t", "description": "", "tags": many}, "video").tags
    assert sum(len(t) for t in kept) + len(kept) - 1 <= 500
    assert len(kept) == 10


def test_finalize_empty_title_becomes_untitled():
    assert finalize({"title": "<>", "description": "", "tags": []}, "video").title == "Untitled"


# --- build_metadata ---

def test_full_sidecar_skips_generator(cfg):
    def generate(stem, kind):
        raise AssertionError("generator must not be called")

    sidecar = ("cake.json", '{"title": "T", "description": "D", "tags": ["x"]}')
    meta = build_metadata("cake", "video", sidecar, generate, cfg)
    assert (meta.title, meta.description, meta.tags) == ("T", "D", ("x",))


def test_generator_fills_missing_fields(cfg):
    calls = []

    def generate(stem, kind):
        calls.append((stem, kind))
        return {"title": "AI title", "description": "AI desc", "tags": ["ai"]}

    meta = build_metadata("cake", "short", ("cake.txt", "My title"), generate, cfg)
    assert calls == [("cake", "short")]
    assert meta.title == "My title"
    assert meta.description == "AI desc\n\n#Shorts"
    assert meta.tags == ("ai",)


def test_generator_failure_uses_fallback(cfg):
    def generate(stem, kind):
        raise RuntimeError("rate limited")

    meta = build_metadata("best_cake", "video", None, generate, cfg)
    assert meta.title == "best cake"
    assert meta.description == "Channel about home cooking."
    assert meta.tags == ("cooking", "recipes")


def test_malformed_sidecar_falls_through_to_generator(cfg):
    def generate(stem, kind):
        return {"title": "AI", "description": "AI", "tags": []}

    meta = build_metadata("cake", "video", ("cake.json", "{broken"), generate, cfg)
    assert meta.title == "AI"


def test_no_generator_uses_fallback(cfg):
    meta = build_metadata("cake", "video", None, None, cfg)
    assert meta.title == "cake"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metadata.py -v`
Expected: `ModuleNotFoundError: No module named 'autopost.metadata'`.

- [ ] **Step 3: Implement `autopost/metadata.py`**

```python
"""Build YouTube metadata: sidecar file first, then generator (Gemini), then config defaults."""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

from autopost.config import Config
from autopost.models import DriveFile, Metadata

log = logging.getLogger(__name__)

TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_MAX = 500
SHORTS_TAG = "#Shorts"
FIELDS = ("title", "description", "tags")

# (file stem, kind) -> dict with any of title/description/tags
Generator = Callable[[str, str], dict]


def parse_sidecar(name: str, text: str) -> dict:
    """Parse a .json or .txt sidecar. Raises ValueError on malformed JSON."""
    if name.lower().endswith(".json"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("sidecar JSON must be an object")
        out: dict = {}
        for key in ("title", "description"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                out[key] = value.strip()
        tags = data.get("tags")
        if isinstance(tags, list):
            clean = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
            if clean:
                out["tags"] = clean
        return out

    lines = text.strip().splitlines()
    if not lines:
        return {}
    out = {"title": lines[0].strip()}
    description = "\n".join(lines[1:]).strip()
    if description:
        out["description"] = description
    return out


def pick_sidecar(files: list[DriveFile]) -> Optional[DriveFile]:
    for ext in (".json", ".txt"):
        for file in files:
            if file.name.lower().endswith(ext):
                return file
    return None


def clean_title(stem: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-.]+", " ", stem)).strip()


def fallback(stem: str, cfg: Config) -> dict:
    return {
        "title": clean_title(stem) or "Untitled",
        "description": cfg.default_description,
        "tags": list(cfg.default_tags),
    }


def _strip_angles(text: str) -> str:
    # YouTube rejects < and > in titles and descriptions
    return text.replace("<", "").replace(">", "")


def _fit_tags(tags: list[str]) -> tuple[str, ...]:
    kept: list[str] = []
    used = 0
    for raw in tags:
        tag = _strip_angles(raw).strip()
        if not tag or tag in kept:
            continue
        # YouTube counts quotes around multi-word tags and commas between tags
        cost = len(tag) + (2 if " " in tag else 0) + (1 if kept else 0)
        if used + cost > TAGS_MAX:
            break
        kept.append(tag)
        used += cost
    return tuple(kept)


def finalize(meta: dict, kind: str) -> Metadata:
    title = _strip_angles(meta["title"]).strip()[:TITLE_MAX].strip() or "Untitled"
    description = _strip_angles(meta["description"]).strip()
    if kind == "short" and SHORTS_TAG.lower() not in description.lower():
        room = DESCRIPTION_MAX - len(SHORTS_TAG) - 2
        description = f"{description[:room]}\n\n{SHORTS_TAG}".strip()
    return Metadata(
        title=title,
        description=description[:DESCRIPTION_MAX],
        tags=_fit_tags(meta["tags"]),
    )


def build_metadata(
    stem: str,
    kind: str,
    sidecar: Optional[tuple[str, str]],
    generate: Optional[Generator],
    cfg: Config,
) -> Metadata:
    """sidecar is (file name, file text) or None."""
    meta: dict = {}
    if sidecar is not None:
        name, text = sidecar
        try:
            meta = parse_sidecar(name, text)
        except ValueError as exc:
            log.warning("ignoring malformed sidecar %s: %s", name, exc)

    missing = [key for key in FIELDS if key not in meta]
    if missing and generate is not None:
        try:
            generated = generate(stem, kind)
            for key in missing:
                if key in generated:
                    meta[key] = generated[key]
        except Exception as exc:  # any AI failure must not block the upload
            log.warning("metadata generator failed for %s: %s", stem, exc)

    defaults = fallback(stem, cfg)
    for key in FIELDS:
        meta.setdefault(key, defaults[key])
    return finalize(meta, kind)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_metadata.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add autopost/metadata.py tests/test_metadata.py
git commit -m "feat: build video metadata from sidecar, AI, or defaults"
```

---

### Task 8: Gemini generator

**Files:**
- Create: `autopost/gemini.py`, `tests/test_gemini.py`

- [ ] **Step 1: Write failing tests `tests/test_gemini.py`**

```python
from types import SimpleNamespace

import pytest

from autopost.gemini import make_gemini


class FakeModels:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(text=self.text)


def client_returning(text):
    return SimpleNamespace(models=FakeModels(text))


def test_generator_parses_json_response():
    client = client_returning('{"title": "Cake", "description": "Yum", "tags": ["cake"]}')
    generate = make_gemini(client, "gemini-flash-latest", "Cooking channel")
    assert generate("best_cake", "short") == {"title": "Cake", "description": "Yum", "tags": ["cake"]}

    call = client.models.calls[0]
    assert call["model"] == "gemini-flash-latest"
    assert "best_cake" in call["contents"]
    assert "Short" in call["contents"]
    assert "Cooking channel" in call["contents"]
    assert call["config"] == {"response_mime_type": "application/json"}


def test_generator_raises_on_bad_json():
    generate = make_gemini(client_returning("sorry, no"), "m", "")
    with pytest.raises(ValueError):
        generate("cake", "video")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gemini.py -v`
Expected: `ModuleNotFoundError: No module named 'autopost.gemini'`.

- [ ] **Step 3: Implement `autopost/gemini.py`**

```python
"""Gemini (free tier) metadata generator. Sees only the file name, never the video."""
from __future__ import annotations

from autopost.metadata import Generator, parse_sidecar

PROMPT = """You write metadata for a YouTube {label}.
Base it only on the file name below. Do not invent specific facts the file name does not suggest.
Return only JSON with these keys:
- "title": catchy, max 90 characters, no all-caps clickbait
- "description": 2-4 short paragraphs, max 1500 characters
- "tags": list of 8-15 short search tags

File name: {stem}
Channel description: {context}
"""

LABELS = {"video": "video", "short": "Short (vertical, under 3 minutes)"}


def make_gemini(client, model: str, context: str) -> Generator:
    """client is a google.genai.Client (or a test fake with the same .models API)."""

    def generate(stem: str, kind: str) -> dict:
        response = client.models.generate_content(
            model=model,
            contents=PROMPT.format(label=LABELS[kind], stem=stem, context=context or "(none)"),
            config={"response_mime_type": "application/json"},
        )
        return parse_sidecar("gemini.json", response.text)

    return generate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gemini.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add autopost/gemini.py tests/test_gemini.py
git commit -m "feat: generate metadata with Gemini"
```

---

### Task 9: YouTube upload

**Files:**
- Create: `autopost/youtube.py`, `tests/test_youtube.py`

- [ ] **Step 1: Write failing tests `tests/test_youtube.py`**

```python
import dataclasses
from datetime import datetime, timezone
from unittest.mock import MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from autopost.models import Metadata
from autopost.youtube import QuotaExceeded, build_body, upload

META = Metadata(title="T", description="D", tags=("a", "b"))
SLOT = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def test_private_mode_has_no_publish_at(cfg):
    body = build_body(META, cfg, SLOT)
    assert body == {
        "snippet": {"title": "T", "description": "D", "tags": ["a", "b"], "categoryId": "26"},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
    }


def test_scheduled_mode_sets_publish_at(cfg):
    scheduled = dataclasses.replace(cfg, publish_mode="scheduled")
    body = build_body(META, scheduled, SLOT)
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-11-19T12:00:00Z"


class FakeRequest:
    def __init__(self, steps):
        self.steps = list(steps)

    def next_chunk(self, num_retries=0):
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def service_with(request):
    service = MagicMock()
    service.videos.return_value.insert.return_value = request
    return service


def http_error(status, content):
    return HttpError(httplib2.Response({"status": status}), content)


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"data")
    return path


def test_upload_returns_video_id_after_chunks(video):
    service = service_with(FakeRequest([(None, None), (None, {"id": "yt123"})]))
    assert upload(service, video, {"snippet": {}}) == "yt123"
    assert service.videos.return_value.insert.call_args.kwargs["part"] == "snippet,status"


@pytest.mark.parametrize("reason", [b"quotaExceeded", b"uploadLimitExceeded"])
def test_quota_errors_raise_quota_exceeded(video, reason):
    service = service_with(FakeRequest([http_error(403, b'{"reason": "' + reason + b'"}')]))
    with pytest.raises(QuotaExceeded):
        upload(service, video, {})


def test_other_http_errors_propagate(video):
    service = service_with(FakeRequest([http_error(400, b"badRequest")]))
    with pytest.raises(HttpError):
        upload(service, video, {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_youtube.py -v`
Expected: `ModuleNotFoundError: No module named 'autopost.youtube'`.

- [ ] **Step 3: Implement `autopost/youtube.py`**

```python
"""YouTube upload: request body + resumable upload."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from autopost.config import Config
from autopost.models import Metadata

UPLOAD_CHUNK = 10 * 1024 * 1024
RETRIES = 3  # retries 5xx/network errors with backoff, resuming from the last chunk
_QUOTA_REASONS = (b"quotaExceeded", b"uploadLimitExceeded", b"dailyLimitExceeded")


class QuotaExceeded(RuntimeError):
    """YouTube daily quota or upload limit reached; stop and retry tomorrow."""


def build_body(meta: Metadata, cfg: Config, publish_at: datetime) -> dict:
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": cfg.made_for_kids}
    if cfg.publish_mode == "scheduled":
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "snippet": {
            "title": meta.title,
            "description": meta.description,
            "tags": list(meta.tags),
            "categoryId": cfg.category_id,
        },
        "status": status,
    }


def upload(service, path: Path, body: dict) -> str:
    """Upload one video; return the new YouTube video ID."""
    media = MediaFileUpload(str(path), chunksize=UPLOAD_CHUNK, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    try:
        while response is None:
            _, response = request.next_chunk(num_retries=RETRIES)
    except HttpError as exc:
        content = exc.content or b""
        if exc.resp.status == 403 and any(reason in content for reason in _QUOTA_REASONS):
            raise QuotaExceeded(content.decode("utf-8", "replace")) from exc
        raise
    return response["id"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_youtube.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add autopost/youtube.py tests/test_youtube.py
git commit -m "feat: add resumable YouTube upload"
```

---

### Task 10: Auth from environment + one-time setup script

**Files:**
- Create: `autopost/auth.py`, `auth_setup.py`, `tests/test_auth.py`

- [ ] **Step 1: Write failing tests `tests/test_auth.py`**

```python
import pytest

from autopost.auth import SCOPES, MissingSecret, credentials_from_env

ENV = {
    "GOOGLE_CLIENT_ID": "cid",
    "GOOGLE_CLIENT_SECRET": "secret",
    "GOOGLE_REFRESH_TOKEN": "refresh",
}


def test_builds_credentials_from_env():
    creds = credentials_from_env(ENV)
    assert creds.client_id == "cid"
    assert creds.client_secret == "secret"
    assert creds.refresh_token == "refresh"
    assert creds.token_uri == "https://oauth2.googleapis.com/token"
    assert list(creds.scopes) == SCOPES


def test_missing_vars_listed():
    with pytest.raises(MissingSecret, match="GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN"):
        credentials_from_env({"GOOGLE_CLIENT_ID": "cid"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_auth.py -v`
Expected: `ModuleNotFoundError: No module named 'autopost.auth'`.

- [ ] **Step 3: Implement `autopost/auth.py`**

```python
"""Google OAuth credentials built from environment variables (GitHub secrets)."""
from __future__ import annotations

import os
from typing import Mapping, Optional

from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/drive",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"
REQUIRED = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")


class MissingSecret(RuntimeError):
    """A required environment variable is not set."""


def credentials_from_env(env: Optional[Mapping[str, str]] = None) -> Credentials:
    env = os.environ if env is None else env
    missing = [key for key in REQUIRED if not env.get(key)]
    if missing:
        raise MissingSecret("missing environment variables: " + ", ".join(missing))
    return Credentials(
        token=None,
        refresh_token=env["GOOGLE_REFRESH_TOKEN"],
        token_uri=TOKEN_URI,
        client_id=env["GOOGLE_CLIENT_ID"],
        client_secret=env["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_auth.py -v`
Expected: all PASS.

- [ ] **Step 5: Create `auth_setup.py`** (manual tool, opens a browser; not unit-tested)

```python
"""One-time local setup: sign in with the channel's Google account and print GitHub secrets.

Usage:
    python auth_setup.py path\\to\\client_secret.json
"""
from __future__ import annotations

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from autopost.auth import SCOPES


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    flow = InstalledAppFlow.from_client_secrets_file(argv[1], scopes=SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        print("No refresh token returned. Remove the app at https://myaccount.google.com/permissions and retry.")
        return 1
    print("\nAdd these as GitHub repository secrets (Settings > Secrets and variables > Actions):\n")
    print(f"GOOGLE_CLIENT_ID={creds.client_id}")
    print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 6: Verify the script loads**

Run: `python auth_setup.py`
Expected: prints the usage docstring, exit code 2.

- [ ] **Step 7: Commit**

```powershell
git add autopost/auth.py auth_setup.py tests/test_auth.py
git commit -m "feat: add OAuth credentials and setup script"
```

---

### Task 11: Notifications

**Files:**
- Create: `autopost/notify.py`, `tests/test_notify.py`

- [ ] **Step 1: Write failing tests `tests/test_notify.py`**

```python
from autopost.notify import send_telegram, write_step_summary


def test_telegram_skipped_without_secrets():
    calls = []
    assert send_telegram("hi", env={}, post=lambda url, payload: calls.append(url)) is False
    assert calls == []


def test_telegram_posts_message():
    calls = []
    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"}
    assert send_telegram("hi", env=env, post=lambda url, payload: calls.append((url, payload))) is True
    assert calls == [("https://api.telegram.org/bottok/sendMessage", {"chat_id": "42", "text": "hi"})]


def test_telegram_failure_is_swallowed():
    def boom(url, payload):
        raise OSError("network down")

    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"}
    assert send_telegram("hi", env=env, post=boom) is False


def test_step_summary_appends(tmp_path):
    path = tmp_path / "summary.md"
    assert write_step_summary("line1", env={"GITHUB_STEP_SUMMARY": str(path)}) is True
    write_step_summary("line2", env={"GITHUB_STEP_SUMMARY": str(path)})
    assert path.read_text(encoding="utf-8") == "line1\nline2\n"


def test_step_summary_skipped_outside_actions():
    assert write_step_summary("x", env={}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notify.py -v`
Expected: `ModuleNotFoundError: No module named 'autopost.notify'`.

- [ ] **Step 3: Implement `autopost/notify.py`**

```python
"""Run summaries: GitHub Actions job summary and optional Telegram message."""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Callable, Mapping, Optional

log = logging.getLogger(__name__)


def _post_json(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def send_telegram(
    text: str,
    env: Optional[Mapping[str, str]] = None,
    post: Callable[[str, dict], None] = _post_json,
) -> bool:
    """Send text to Telegram if both secrets are set. Never raises."""
    env = os.environ if env is None else env
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        post(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat_id, "text": text})
        return True
    except Exception as exc:
        log.warning("Telegram notification failed: %s", type(exc).__name__)
        return False


def write_step_summary(text: str, env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    path = env.get("GITHUB_STEP_SUMMARY")
    if not path:
        return False
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return True
```

Only the exception type is logged, so the bot token (part of the URL) can never leak into logs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notify.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add autopost/notify.py tests/test_notify.py
git commit -m "feat: add run summary notifications"
```

---

### Task 12: Run orchestration

**Files:**
- Create: `autopost/main.py` (run + format_summary only; CLI added in Task 13), `tests/test_main.py`

- [ ] **Step 1: Write failing tests `tests/test_main.py`**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py -v`
Expected: `ModuleNotFoundError: No module named 'autopost.main'`.

- [ ] **Step 3: Implement `autopost/main.py`**

```python
"""One autopost run: plan today's slots, upload, record, move, summarize."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from autopost.config import Config
from autopost.drive import split_listing
from autopost.ledger import Ledger
from autopost.metadata import Generator, build_metadata, pick_sidecar
from autopost.models import DriveFile, Job
from autopost.scheduler import plan_day
from autopost.youtube import QuotaExceeded, build_body

log = logging.getLogger("autopost")
KINDS = ("video", "short")

Uploader = Callable[[Path, dict], str]


@dataclass
class RunResult:
    planned: list[Job] = field(default_factory=list)
    uploaded: list[tuple[Job, str]] = field(default_factory=list)
    failed: list[tuple[Job, str]] = field(default_factory=list)
    quota_hit: bool = False
    queue_left: dict[str, int] = field(default_factory=dict)


def _stem(file: DriveFile) -> str:
    return os.path.splitext(file.name)[0]


def _queue_folder(cfg: Config, kind: str) -> str:
    return cfg.queue_videos_folder_id if kind == "video" else cfg.queue_shorts_folder_id


def _move_with_sidecars(drive, video: DriveFile, sidecars: list[DriveFile], src: str, dst: str) -> None:
    for file in [video, *sidecars]:
        drive.move(file.id, src, dst)


def _read_sidecar(drive, files: list[DriveFile]) -> Optional[tuple[str, str]]:
    chosen = pick_sidecar(files)
    if chosen is None:
        return None
    try:
        return chosen.name, drive.read_text(chosen.id)
    except Exception as exc:
        log.warning("could not read sidecar %s: %s", chosen.name, exc)
        return None


def run(
    cfg: Config,
    drive,
    uploader: Uploader,
    ledger: Ledger,
    generate: Optional[Generator],
    now: datetime,
    dry_run: bool,
    workdir: Path,
) -> RunResult:
    pending: dict[str, list[DriveFile]] = {}
    sidecars: dict[str, dict[str, list[DriveFile]]] = {}
    for kind in KINDS:
        folder = _queue_folder(cfg, kind)
        videos, sidecars[kind] = split_listing(drive.list_folder(folder))
        pending[kind] = []
        for video in videos:
            if not ledger.has(video.id):
                pending[kind].append(video)
                continue
            if dry_run:
                continue
            # uploaded on an earlier run but the move failed: retry the move only
            try:
                _move_with_sidecars(drive, video, sidecars[kind].get(_stem(video), []), folder, cfg.posted_folder_id)
            except Exception as exc:
                log.warning("could not move already-posted %s: %s", video.name, exc)

    today = now.astimezone(cfg.timezone).date()
    result = RunResult(planned=plan_day(today, now, cfg, pending["video"], pending["short"]))

    for job in result.planned:
        stem = _stem(job.file)
        folder = _queue_folder(cfg, job.kind)
        side_files = sidecars[job.kind].get(stem, [])
        meta = build_metadata(stem, job.kind, _read_sidecar(drive, side_files), generate, cfg)
        if dry_run:
            log.info("[dry-run] %s %s at %s -> %r", job.kind, job.file.name, job.publish_at.isoformat(), meta.title)
            continue

        path = workdir / f"{job.file.id}{Path(job.file.name).suffix}"
        try:
            drive.download(job.file.id, path)
            video_id = uploader(path, build_body(meta, cfg, job.publish_at))
        except QuotaExceeded as exc:
            log.warning("YouTube quota reached, stopping: %s", exc)
            result.quota_hit = True
            break
        except Exception as exc:
            log.error("failed %s: %s", job.file.name, exc)
            result.failed.append((job, str(exc)))
            continue
        finally:
            path.unlink(missing_ok=True)

        ledger.add(job.file.id, video_id, job.publish_at, datetime.now(timezone.utc))
        result.uploaded.append((job, video_id))
        log.info("uploaded %s %s -> %s", job.kind, job.file.name, video_id)
        try:
            _move_with_sidecars(drive, job.file, side_files, folder, cfg.posted_folder_id)
        except Exception as exc:
            log.warning("uploaded %s but move failed (retried next run): %s", job.file.name, exc)

    done = {kind: sum(1 for job, _ in result.uploaded if job.kind == kind) for kind in KINDS}
    result.queue_left = {kind: len(pending[kind]) - done[kind] for kind in KINDS}
    return result


def format_summary(result: RunResult, dry_run: bool) -> str:
    head = "autopost dry run" if dry_run else "autopost run"
    lines = [
        f"{head}: {len(result.uploaded)} uploaded, {len(result.failed)} failed, {len(result.planned)} planned"
    ]
    for job, video_id in result.uploaded:
        lines.append(f"- uploaded {job.kind} {job.file.name} -> https://youtu.be/{video_id}")
    for job, error in result.failed:
        lines.append(f"- FAILED {job.kind} {job.file.name}: {error}")
    if result.quota_hit:
        lines.append("- stopped: YouTube daily quota reached")
    if dry_run:
        for job in result.planned:
            lines.append(f"- would upload {job.kind} {job.file.name} at {job.publish_at:%Y-%m-%d %H:%M} UTC")
    left = result.queue_left
    lines.append(f"Queue left: {left.get('video', 0)} videos, {left.get('short', 0)} shorts")
    if not any(left.values()):
        lines.append("Queue empty: add more files to Drive.")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add autopost/main.py tests/test_main.py
git commit -m "feat: orchestrate one autopost run"
```

---

### Task 13: CLI entry point

**Files:**
- Modify: `autopost/main.py` (append `main()` and `_make_generator()`; add imports)
- Create: `autopost/__main__.py`
- Test: `tests/test_main.py` (append)

- [ ] **Step 1: Append failing test to `tests/test_main.py`**

```python
def test_cli_help_exits_zero(capsys):
    from autopost.main import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "--dry-run" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py::test_cli_help_exits_zero -v`
Expected: FAIL with `ImportError: cannot import name 'main'`.

- [ ] **Step 3: Add imports at the top of `autopost/main.py`**

Replace the import block with:

```python
import argparse
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build

from autopost.auth import MissingSecret, credentials_from_env
from autopost.config import Config, load_config
from autopost.drive import Drive, split_listing
from autopost.ledger import Ledger
from autopost.metadata import Generator, build_metadata, pick_sidecar
from autopost.models import DriveFile, Job
from autopost.notify import send_telegram, write_step_summary
from autopost.scheduler import plan_day
from autopost.youtube import QuotaExceeded, build_body, upload
```

(keep `from __future__ import annotations` as the first line.)

- [ ] **Step 4: Append to the end of `autopost/main.py`**

```python
def _make_generator(cfg: Config) -> Optional[Generator]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        log.warning("GEMINI_API_KEY not set: using fallback metadata")
        return None
    from google import genai

    from autopost.gemini import make_gemini

    return make_gemini(genai.Client(api_key=key), cfg.gemini_model, cfg.default_description)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="autopost", description="Upload queued Google Drive videos to YouTube.")
    parser.add_argument("--dry-run", action="store_true", help="plan and generate metadata only; upload nothing")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--ledger", default="posted_log.json", help="path to posted_log.json")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(args.config)
    try:
        creds = credentials_from_env()
        drive = Drive(build("drive", "v3", credentials=creds, cache_discovery=False))
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        with tempfile.TemporaryDirectory() as tmp:
            result = run(
                cfg,
                drive,
                lambda path, body: upload(youtube, path, body),
                Ledger(args.ledger),
                _make_generator(cfg),
                datetime.now(timezone.utc),
                args.dry_run,
                Path(tmp),
            )
    except MissingSecret as exc:
        log.error("%s. Add them as GitHub repository secrets.", exc)
        return 1
    except RefreshError as exc:
        log.error(
            "Google auth failed (%s). Re-run auth_setup.py and update the GOOGLE_REFRESH_TOKEN secret.", exc
        )
        return 1

    text = format_summary(result, args.dry_run)
    print(text)
    write_step_summary(text)
    send_telegram(text)
    return 1 if result.failed else 0
```

- [ ] **Step 5: Create `autopost/__main__.py`**

```python
from autopost.main import main

raise SystemExit(main())
```

- [ ] **Step 6: Run full suite and the CLI**

Run:
```powershell
python -m pytest -v
python -m autopost --help
```
Expected: all tests PASS; help text lists `--dry-run`, `--config`, `--ledger`.

- [ ] **Step 7: Commit**

```powershell
git add autopost/main.py autopost/__main__.py tests/test_main.py
git commit -m "feat: add autopost CLI entry point"
```

---

### Task 14: Config file and GitHub Actions workflow

**Files:**
- Create: `config.yaml`, `.github/workflows/autopost.yml`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Append failing test to `tests/test_config.py`**

```python
def test_repo_config_yaml_is_valid():
    from pathlib import Path

    cfg = load_config(Path(__file__).parent.parent / "config.yaml")
    assert len(cfg.video_slots) + len(cfg.short_slots) <= cfg.daily_cap
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_repo_config_yaml_is_valid -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Create `config.yaml`**

```yaml
# Autopost settings. Times are 24h and MUST be in quotes ("18:00"), otherwise YAML misreads them.

timezone: Asia/Dhaka            # your channel's IANA timezone
publish_mode: private           # private = upload as private drafts (before API audit)
                                # scheduled = private + auto-publish at slot time (after audit)
daily_cap: 6                    # 1..6 (YouTube free API quota allows ~6 uploads/day)

slots:                          # each slot must be later than 06:30; total slots <= daily_cap
  videos: ["18:00"]
  shorts: ["10:00", "13:00", "16:00", "20:00", "22:00"]

drive:                          # folder ID = the last part of the folder's URL in Drive
  queue_videos_folder_id: "REPLACE_WITH_QUEUE_VIDEOS_FOLDER_ID"
  queue_shorts_folder_id: "REPLACE_WITH_QUEUE_SHORTS_FOLDER_ID"
  posted_folder_id: "REPLACE_WITH_POSTED_FOLDER_ID"

defaults:                       # used when no sidecar and Gemini is unavailable
  description: ""
  tags: []
  category_id: "22"             # 22 = People & Blogs
  made_for_kids: false

gemini_model: gemini-flash-latest
```

The `REPLACE_WITH_...` values are filled in by the user during setup (README step 6); they pass validation as non-empty strings so tests run before setup.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 5: Create `.github/workflows/autopost.yml`**

```yaml
name: autopost

on:
  schedule:
    # GitHub cron is UTC. This is 06:00 in Asia/Dhaka (UTC+6).
    # For another timezone: 06:00 local converted to UTC, as "MINUTE HOUR * * *".
    - cron: "0 0 * * *"
  workflow_dispatch:
    inputs:
      dry_run:
        description: "Plan only, upload nothing"
        type: boolean
        default: false

permissions:
  contents: write   # commit posted_log.json back

concurrency:
  group: autopost
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install
        run: pip install -r requirements.txt

      - name: Run autopost
        env:
          GOOGLE_CLIENT_ID: ${{ secrets.GOOGLE_CLIENT_ID }}
          GOOGLE_CLIENT_SECRET: ${{ secrets.GOOGLE_CLIENT_SECRET }}
          GOOGLE_REFRESH_TOKEN: ${{ secrets.GOOGLE_REFRESH_TOKEN }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python -m autopost ${{ inputs.dry_run && '--dry-run' || '' }}

      - name: Commit ledger
        if: always()
        run: |
          git config user.name "autopost-bot"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add posted_log.json
          git diff --cached --quiet || (git commit -m "chore: update posted log [skip ci]" && git push)
```

- [ ] **Step 6: Commit**

```powershell
git add config.yaml .github/workflows/autopost.yml tests/test_config.py
git commit -m "feat: add config file and daily GitHub Actions workflow"
```

---

### Task 15: Docs (README, policy pages, audit notes)

**Files:**
- Create: `README.md`, `docs/policy/privacy-policy.md`, `docs/policy/terms.md`, `docs/audit-notes.md`

- [ ] **Step 1: Create `docs/policy/privacy-policy.md`**

```markdown
# Privacy Policy: Autopost

_Last updated: 2026-11-19_

Autopost is a personal tool that uploads videos from the owner's Google Drive to the owner's own YouTube channel. It has one user: the channel owner.

## What data it uses
- **Google account access (OAuth):** permission to read and move files in Google Drive and to upload videos to YouTube. The access token is stored only as an encrypted GitHub Actions secret in the owner's private repository.
- **Video files:** downloaded from Drive to a temporary GitHub Actions runner, uploaded to YouTube, then deleted from the runner when the run ends.
- **File names:** sent to the Google Gemini API to draft titles, descriptions and tags.
- **Upload log:** Drive file IDs and YouTube video IDs are kept in the owner's private repository to prevent duplicate uploads.

## What it does not do
- It does not collect data from anyone other than the owner.
- It does not sell, share or transfer data to third parties.
- It does not use YouTube data for advertising or analytics.

## YouTube API Services
Autopost uses YouTube API Services. By using it you agree to the [YouTube Terms of Service](https://www.youtube.com/t/terms). See also the [Google Privacy Policy](https://policies.google.com/privacy).

You can revoke Autopost's access at any time at [Google security settings](https://myaccount.google.com/permissions).

## Contact
CONTACT_EMAIL
```

- [ ] **Step 2: Create `docs/policy/terms.md`**

```markdown
# Terms of Use: Autopost

_Last updated: 2026-11-19_

Autopost is a private tool operated by the channel owner for uploading the owner's own videos to the owner's own YouTube channel. It is not offered to the public.

By using Autopost, the user agrees to the [YouTube Terms of Service](https://www.youtube.com/t/terms) and the [Google Privacy Policy](https://policies.google.com/privacy).

The owner is responsible for having the rights to every video uploaded.

Contact: CONTACT_EMAIL
```

- [ ] **Step 3: Create `docs/audit-notes.md`**

```markdown
# YouTube API audit: answers to paste

**Form:** YouTube API Services – Audit and Quota Extension Form (linked from the YouTube Data API docs, "Quota and Compliance Audits").

**App name:** Autopost

**What does your app do?**
Autopost is a single-user, internal tool. Each day it takes video files that I (the channel owner) placed in my own Google Drive folder and uploads them to my own YouTube channel with `videos.insert`, scheduled with `status.publishAt`. Titles, descriptions and tags come from a text file I write next to each video, or are drafted from the file name. It runs as a scheduled GitHub Actions job in my private repository.

**Who are the users?** Only me, the channel owner. No other users, no public sign-up.

**Which API methods?** `videos.insert` (part=snippet,status). No reads of other channels' data.

**Data storage:** No YouTube data is stored except the IDs of my own uploaded videos, kept in a log file in my private repository to prevent duplicate uploads.

**Privacy policy URL:** <your GitHub Pages URL>/privacy-policy
**Terms URL:** <your GitHub Pages URL>/terms

**Quota needed:** Default 10,000 units/day is enough (max 6 uploads/day). Requesting audit only to lift the private-only restriction on uploads from an unverified project.
```

- [ ] **Step 4: Create `README.md`**

````markdown
# Autopost: Google Drive → YouTube, on a schedule, for free

Every morning a GitHub Actions job takes the next files from your Drive queue folders and uploads them to YouTube for today's time slots (max 6 per day).

- `queue/videos/` → regular videos, `queue/shorts/` → Shorts
- Optional sidecar next to a video: `my-video.json` (`{"title": ..., "description": ..., "tags": [...]}`) or `my-video.txt` (line 1 = title, rest = description). Missing fields are written by Gemini from the file name; if Gemini fails, defaults from `config.yaml` are used.
- After upload, the video and its sidecar move to `posted/`. `posted_log.json` prevents duplicates.

## Modes

| `publish_mode` | What happens | When to use |
|---|---|---|
| `private` | All of today's uploads happen at the 06:00 run, as private videos with metadata filled in. You publish them in YouTube Studio. | Until the YouTube API audit is approved |
| `scheduled` | Same, plus YouTube auto-publishes each video at its slot time (`publishAt`). | After audit approval |

## One-time setup (≈45 min, all free)

1. **Google Cloud project:** at https://console.cloud.google.com create a project. Under *APIs & Services → Library*, enable **YouTube Data API v3** and **Google Drive API**.
2. **OAuth consent screen:** User type *External*. Add scopes `.../auth/youtube.upload` and `.../auth/drive`. Add your channel's Google account as a test user. Then click **Publish app** so the status is **In production** (otherwise the token expires every 7 days). You will see an "unverified app" warning when signing in; click *Advanced → Go to app*. That's fine for a single-user tool.
3. **OAuth client:** *Credentials → Create credentials → OAuth client ID → Desktop app*. Download the JSON as `client_secret.json` into this folder (it's gitignored).
4. **Refresh token:**
   ```powershell
   python -m venv .venv; .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python auth_setup.py client_secret.json
   ```
   Sign in with the **channel's** Google account. Copy the three printed values.
5. **Gemini key:** https://aistudio.google.com → *Get API key* (free tier).
6. **Drive folders:** create `autopost/queue/videos`, `autopost/queue/shorts`, `autopost/posted`. Open each and copy the ID from the URL (`drive.google.com/drive/folders/<ID>`) into `config.yaml`. Set `timezone` and `slots` there too.
7. **Cron time:** in `.github/workflows/autopost.yml` set the cron to 06:00 *your* time in UTC. Examples: Asia/Dhaka `0 0 * * *`, Asia/Kolkata `30 0 * * *`, Europe/London (winter) `0 6 * * *`, America/New_York (winter) `0 11 * * *`.
8. **GitHub:** create a **private** repo, push this folder, then add secrets under *Settings → Secrets and variables → Actions*: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `GEMINI_API_KEY`. Optional: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (create a bot with @BotFather; get your chat ID from @userinfobot).
9. **Test:** *Actions → autopost → Run workflow* with **dry_run** ticked. Check the plan in the job summary. Then put one small test video in `queue/shorts`, run again without dry run, and confirm: private video in Studio, metadata filled in, file moved to `posted/`, new commit updating `posted_log.json`.

## API audit (to auto-publish)

GitHub Pages is free only for **public** repos, so host the policy pages separately:
1. Replace `CONTACT_EMAIL` in `docs/policy/privacy-policy.md` and `docs/policy/terms.md` with your contact email.
2. Create a new **public** repo (e.g. `autopost-policy`), copy both files into it, enable *Settings → Pages* (branch `main`, root).
3. Fill in the YouTube API audit form using `docs/audit-notes.md`, with your Pages URLs.
4. After approval: set `publish_mode: scheduled` in `config.yaml` and push.

## Limits and costs

- YouTube API: 10,000 units/day free ≈ 6 uploads. `daily_cap` enforces it.
- GitHub Actions private repo: 2,000 free minutes/month; one run ≈ 2–10 min depending on file sizes.
- Gemini: free tier; one short request per video.
- Runner disk ≈ 14 GB free; each video is deleted right after upload.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Run fails with "Google auth failed" | Run `python auth_setup.py client_secret.json` again and update `GOOGLE_REFRESH_TOKEN`. Check the consent screen is *In production*. |
| "stopped: YouTube daily quota reached" | Normal if many uploads failed and retried; leftovers go tomorrow. |
| Uploaded videos stuck private | Expected until the API audit is approved. |
| Slot error in config | Times must be quoted (`"18:00"`) and later than 06:30. |
| Nothing uploads, "Queue empty" | Add files to `queue/videos` or `queue/shorts`. |

## Development

```powershell
python -m pytest -v
python -m autopost --dry-run   # needs the GOOGLE_* env vars set locally
```
````

- [ ] **Step 5: Commit**

```powershell
git add README.md docs/policy docs/audit-notes.md
git commit -m "docs: add setup guide, policy pages, and audit notes"
```

---

### Task 16: Final verification

- [ ] **Step 1: Full test run**

Run: `python -m pytest -v`
Expected: all tests PASS, zero failures.

- [ ] **Step 2: CLI smoke check**

Run: `python -m autopost --help`
Expected: usage text with `--dry-run`, `--config`, `--ledger`.

- [ ] **Step 3: Missing-secret behavior**

Run (PowerShell, with no GOOGLE_* vars set):
```powershell
Remove-Item Env:GOOGLE_CLIENT_ID, Env:GOOGLE_CLIENT_SECRET, Env:GOOGLE_REFRESH_TOKEN -ErrorAction SilentlyContinue
python -m autopost --dry-run; $LASTEXITCODE
```
Expected: log line `ERROR missing environment variables: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN. Add them as GitHub repository secrets.` and exit code `1`.

- [ ] **Step 4: Workflow YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/autopost.yml', encoding='utf-8')); print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit any fixes**

If steps 1–4 required changes:
```powershell
git add -A
git commit -m "fix: address final verification issues"
```

Live Google setup and the smoke test (README steps 1–9) are done by the user; they need the user's Google account and cannot be automated here.
