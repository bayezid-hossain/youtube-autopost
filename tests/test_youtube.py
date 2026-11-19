import dataclasses
from datetime import datetime, timezone
from unittest.mock import MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from autopost.models import Metadata
from autopost.youtube import QuotaExceeded, build_body, upload

META = Metadata(title="T", description="D", tags=("a", "b"))
SLOT = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def test_private_mode_has_no_publish_at(cfg):
    body = build_body(META, cfg, SLOT)
    assert body == {
        "snippet": {"title": "T", "description": "D", "tags": ["a", "b"], "categoryId": "26"},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
    }


def test_scheduled_mode_sets_publish_at(cfg):
    scheduled = dataclasses.replace(cfg, publish_mode="scheduled")
    body = build_body(META, scheduled, SLOT)
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-11-19T12:00:00Z"


class FakeRequest:
    def __init__(self, steps):
        self.steps = list(steps)

    def next_chunk(self, num_retries=0):
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def service_with(request):
    service = MagicMock()
    service.videos.return_value.insert.return_value = request
    return service


def http_error(status, content):
    return HttpError(httplib2.Response({"status": status}), content)


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"data")
    return path


def test_upload_returns_video_id_after_chunks(video):
    service = service_with(FakeRequest([(None, None), (None, {"id": "yt123"})]))
    assert upload(service, video, {"snippet": {}}) == "yt123"
    assert service.videos.return_value.insert.call_args.kwargs["part"] == "snippet,status"


@pytest.mark.parametrize("reason", [b"quotaExceeded", b"uploadLimitExceeded"])
def test_quota_errors_raise_quota_exceeded(video, reason):
    service = service_with(FakeRequest([http_error(403, b'{"reason": "' + reason + b'"}')]))
    with pytest.raises(QuotaExceeded):
        upload(service, video, {})


def test_other_http_errors_propagate(video):
    service = service_with(FakeRequest([http_error(400, b"badRequest")]))
    with pytest.raises(HttpError):
        upload(service, video, {})
