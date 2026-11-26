import dataclasses
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

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


@pytest.mark.parametrize(
    "day, expected_utc_hour",
    [(date(2026, 7, 15), 22), (date(2026, 11, 19), 23)],  # EDT = UTC-4, EST = UTC-5
)
def test_publish_at_respects_dst(cfg, day, expected_utc_hour):
    ny = dataclasses.replace(cfg, timezone=ZoneInfo("America/New_York"), video_slots=(time(18, 0),), short_slots=())
    now = datetime(day.year, day.month, day.day, 0, 0, tzinfo=timezone.utc)
    jobs = plan_day(day, now, ny, [f("v1")], [])
    assert [j.publish_at for j in jobs] == [
        datetime(day.year, day.month, day.day, expected_utc_hour, tzinfo=timezone.utc)
    ]


def test_project_queue_spreads_files_over_following_days(cfg):
    from autopost.scheduler import project_queue

    cfg = dataclasses.replace(cfg, video_slots=(time(9, 0), time(18, 0)), short_slots=(), daily_cap=2)
    tz = cfg.timezone
    files = [DriveFile(str(i), f"{i}.mp4", f"2026-11-0{i}T00:00:00Z") for i in range(1, 6)]
    now = datetime(2026, 11, 26, 12, 0, tzinfo=tz)  # 09:00 already passed today
    jobs = project_queue(date(2026, 11, 26), now, cfg, files, [])
    got = [(j.file.id, j.publish_at.astimezone(tz).strftime("%m-%d %H:%M")) for j in jobs]
    assert got == [
        ("1", "11-26 18:00"),
        ("2", "11-27 09:00"),
        ("3", "11-27 18:00"),
        ("4", "11-28 09:00"),
        ("5", "11-28 18:00"),
    ]


def test_project_queue_without_slots_returns_nothing(cfg):
    from autopost.scheduler import project_queue

    cfg = dataclasses.replace(cfg, video_slots=(), short_slots=())
    now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    assert project_queue(date(2026, 11, 26), now, cfg, [DriveFile("1", "a.mp4", "t")], [], max_days=5) == []
