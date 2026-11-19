"""Run summaries: GitHub Actions job summary and optional Telegram message."""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Callable, Mapping, Optional

log = logging.getLogger(__name__)


def _post_json(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def send_telegram(
    text: str,
    env: Optional[Mapping[str, str]] = None,
    post: Callable[[str, dict], None] = _post_json,
) -> bool:
    """Send text to Telegram if both secrets are set. Never raises."""
    env = os.environ if env is None else env
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        post(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat_id, "text": text})
        return True
    except Exception as exc:
        log.warning("Telegram notification failed: %s", type(exc).__name__)
        return False


def write_step_summary(text: str, env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    path = env.get("GITHUB_STEP_SUMMARY")
    if not path:
        return False
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return True
