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


@pytest.mark.parametrize("value", ["false", "true", 0, 1, "no"])
def test_made_for_kids_must_be_bool(raw_config, value):
    raw_config["defaults"]["made_for_kids"] = value
    with pytest.raises(ConfigError, match="made_for_kids must be true or false"):
        parse_config(raw_config)


def test_made_for_kids_true_accepted(raw_config):
    raw_config["defaults"]["made_for_kids"] = True
    assert parse_config(raw_config).made_for_kids is True


@pytest.mark.parametrize("value", ["cooking", {"a": 1}, 5])
def test_tags_must_be_list(raw_config, value):
    raw_config["defaults"]["tags"] = value
    with pytest.raises(ConfigError, match="defaults.tags"):
        parse_config(raw_config)


def test_null_tags_means_empty(raw_config):
    raw_config["defaults"]["tags"] = None
    assert parse_config(raw_config).default_tags == ()


def test_null_description_and_model_use_defaults(raw_config):
    raw_config["defaults"]["description"] = None
    raw_config["gemini_model"] = None
    cfg = parse_config(raw_config)
    assert cfg.default_description == ""
    assert cfg.gemini_model == "gemini-flash-latest"


@pytest.mark.parametrize("slots", ["18:00", ["18:00"]])
def test_slots_must_be_mapping(raw_config, slots):
    raw_config["slots"] = slots
    with pytest.raises(ConfigError, match="slots"):
        parse_config(raw_config)


@pytest.mark.parametrize("kind", ["videos", "shorts"])
def test_duplicate_slot_rejected(raw_config, kind):
    raw_config["slots"][kind] = ["18:00", "18:00"]
    with pytest.raises(ConfigError, match="duplicate"):
        parse_config(raw_config)


def test_video_and_short_at_same_time_allowed(raw_config):
    raw_config["slots"] = {"videos": ["18:00"], "shorts": ["18:00"]}
    cfg = parse_config(raw_config)
    assert cfg.video_slots == cfg.short_slots == (time(18, 0),)
