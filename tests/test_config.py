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
