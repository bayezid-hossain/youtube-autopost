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
