"""Load and validate config.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

MAX_DAILY_UPLOADS = 6  # YouTube free quota: 10,000 units/day, ~1,600 per upload
EARLIEST_SLOT = time(6, 30)  # daily run starts 06:00 local and needs lead time
PUBLISH_MODES = ("private", "scheduled", "public")
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ConfigError(ValueError):
    """config.yaml is missing a value or has an invalid one."""


@dataclass(frozen=True)
class Config:
    timezone: ZoneInfo
    publish_mode: str
    daily_cap: int
    video_slots: tuple[time, ...]
    short_slots: tuple[time, ...]
    queue_videos_folder_id: Optional[str]  # required only when slots.videos is non-empty
    queue_shorts_folder_id: Optional[str]  # required only when slots.shorts is non-empty
    posted_folder_id: Optional[str]  # None: never move files (e.g. read-only shared folder)
    default_description: str
    default_tags: tuple[str, ...]
    category_id: str
    made_for_kids: bool
    gemini_model: str
    hashtags_file: Optional[str] = None  # file name inside a queue folder


def _optional_id(drive: dict, key: str) -> Optional[str]:
    value = drive.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigError(f"drive.{key} must be a folder ID string")
    return value


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


def _parse_slot_list(values, name: str) -> tuple[time, ...]:
    if values is None:
        values = []
    if not isinstance(values, list):
        raise ConfigError(f"slots.{name} must be a list of HH:MM times")
    parsed = [_parse_slot(v) for v in values]
    if len(set(parsed)) != len(parsed):
        raise ConfigError(f"duplicate time in slots.{name}")
    return tuple(sorted(parsed))


def parse_config(raw: dict) -> Config:
    tz = _parse_timezone(raw.get("timezone"))

    mode = raw.get("publish_mode", "private")
    if mode not in PUBLISH_MODES:
        raise ConfigError(f"publish_mode must be one of {PUBLISH_MODES}, got {mode!r}")

    cap = raw.get("daily_cap", MAX_DAILY_UPLOADS)
    if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= MAX_DAILY_UPLOADS:
        raise ConfigError(f"daily_cap must be an integer 1..{MAX_DAILY_UPLOADS}, got {cap!r}")

    slots = raw.get("slots")
    if slots is None:
        slots = {}
    if not isinstance(slots, dict):
        raise ConfigError("slots must be a mapping with videos and/or shorts lists")
    video_slots = _parse_slot_list(slots.get("videos"), "videos")
    short_slots = _parse_slot_list(slots.get("shorts"), "shorts")
    total = len(video_slots) + len(short_slots)
    if total == 0:
        raise ConfigError("at least one slot is required under slots.videos or slots.shorts")
    if total > cap:
        raise ConfigError(f"{total} slots configured but daily_cap is {cap}")

    drive = raw.get("drive") or {}
    if not isinstance(drive, dict):
        raise ConfigError("drive must be a mapping of folder IDs")
    videos_folder = _optional_id(drive, "queue_videos_folder_id")
    shorts_folder = _optional_id(drive, "queue_shorts_folder_id")
    if video_slots and videos_folder is None:
        raise ConfigError("drive.queue_videos_folder_id is required when slots.videos is set")
    if short_slots and shorts_folder is None:
        raise ConfigError("drive.queue_shorts_folder_id is required when slots.shorts is set")

    hashtags_file = raw.get("hashtags_file")
    if hashtags_file is not None and not isinstance(hashtags_file, str):
        raise ConfigError("hashtags_file must be a file name, e.g. Hash_Tag.txt")

    defaults = raw.get("defaults") or {}

    made_for_kids = defaults.get("made_for_kids", False)
    if not isinstance(made_for_kids, bool):
        raise ConfigError("defaults.made_for_kids must be true or false")
    tags = defaults.get("tags")
    if tags is None:
        tags = []
    if not isinstance(tags, list):
        raise ConfigError("defaults.tags must be a list of strings")
    return Config(
        timezone=tz,
        publish_mode=mode,
        daily_cap=cap,
        video_slots=video_slots,
        short_slots=short_slots,
        queue_videos_folder_id=videos_folder,
        queue_shorts_folder_id=shorts_folder,
        posted_folder_id=_optional_id(drive, "posted_folder_id"),
        default_description=str(defaults.get("description") or ""),
        default_tags=tuple(str(t) for t in tags),
        category_id=str(defaults.get("category_id", "22")),
        made_for_kids=made_for_kids,
        gemini_model=str(raw.get("gemini_model") or "gemini-3.8-flash"),
        hashtags_file=hashtags_file or None,
    )


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml must be a mapping of keys to values")
    return parse_config(raw)
