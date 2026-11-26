"""Map today's time slots onto the next files in each queue."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

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


def project_queue(
    start_day: date,
    now: datetime,
    cfg: Config,
    videos: list[DriveFile],
    shorts: list[DriveFile],
    max_days: int = 3650,
) -> list[Job]:
    """Expected publish slot for every queued file, day by day from start_day, in queue order."""
    videos, shorts = list(videos), list(shorts)
    jobs: list[Job] = []
    day = start_day
    for _ in range(max_days):
        if not videos and not shorts:
            break
        todays = plan_day(day, now, cfg, videos, shorts)
        jobs.extend(todays)
        used = {job.file.id for job in todays}
        videos = [f for f in videos if f.id not in used]
        shorts = [f for f in shorts if f.id not in used]
        day += timedelta(days=1)
    return jobs
