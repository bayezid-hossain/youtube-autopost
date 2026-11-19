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
