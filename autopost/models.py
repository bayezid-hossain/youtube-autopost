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
