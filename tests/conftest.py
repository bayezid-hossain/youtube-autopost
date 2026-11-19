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
