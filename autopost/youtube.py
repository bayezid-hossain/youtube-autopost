"""YouTube upload: request body + resumable upload."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from autopost.config import Config
from autopost.models import Metadata

UPLOAD_CHUNK = 10 * 1024 * 1024
RETRIES = 3  # retries 5xx/network errors with backoff, resuming from the last chunk
_QUOTA_REASONS = (b"quotaExceeded", b"uploadLimitExceeded", b"dailyLimitExceeded")


class QuotaExceeded(RuntimeError):
    """YouTube daily quota or upload limit reached; stop and retry tomorrow."""


def build_body(meta: Metadata, cfg: Config, publish_at: datetime) -> dict:
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": cfg.made_for_kids}
    if cfg.publish_mode == "scheduled":
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "snippet": {
            "title": meta.title,
            "description": meta.description,
            "tags": list(meta.tags),
            "categoryId": cfg.category_id,
        },
        "status": status,
    }


def upload(service, path: Path, body: dict) -> str:
    """Upload one video; return the new YouTube video ID."""
    media = MediaFileUpload(str(path), chunksize=UPLOAD_CHUNK, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    try:
        while response is None:
            _, response = request.next_chunk(num_retries=RETRIES)
    except HttpError as exc:
        content = exc.content or b""
        if exc.resp.status == 403 and any(reason in content for reason in _QUOTA_REASONS):
            raise QuotaExceeded(content.decode("utf-8", "replace")) from exc
        raise
    return response["id"]
