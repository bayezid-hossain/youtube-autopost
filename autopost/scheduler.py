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
