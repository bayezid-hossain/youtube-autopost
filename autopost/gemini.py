"""Gemini (free tier) metadata generator. Sees only the file name, never the video."""
from __future__ import annotations

import logging
import time
from typing import Callable, Sequence

from autopost.metadata import Generator, parse_sidecar

log = logging.getLogger(__name__)

PROMPT = """You write metadata for a YouTube {label}.
Base it only on the file name below. Do not invent specific facts the file name does not suggest.
Return only JSON with these keys:
- "title": catchy, max 90 characters, no all-caps clickbait
- "description": 2-4 short paragraphs, max 1500 characters, no hashtags (they are added separately)
- "tags": list of 8-15 short search tags

File name: {stem}
Channel description: {context}
"""

LABELS = {"video": "video", "short": "Short (vertical, under 3 minutes)"}

# Free-tier models often return 503 "high demand"; a lighter model is a better fallback than a file-name title.
DEFAULT_FALLBACKS = ("gemini-3.5-flash-lite",)
ATTEMPTS_PER_MODEL = 2
RETRY_DELAY_SECONDS = 5


def make_gemini(
    client,
    model: str,
    context: str,
    fallbacks: Sequence[str] = DEFAULT_FALLBACKS,
    sleep: Callable[[float], None] = time.sleep,
) -> Generator:
    """client is a google.genai.Client (or a test fake with the same .models API)."""
    models = [model, *(m for m in fallbacks if m != model)]

    def call(name: str, stem: str, kind: str):
        return client.models.generate_content(
            model=name,
            contents=PROMPT.format(label=LABELS[kind], stem=stem, context=context or "(none)"),
            config={"response_mime_type": "application/json"},
        )

    def generate(stem: str, kind: str) -> dict:
        last_error: Exception | None = None
        for name in models:
            for attempt in range(ATTEMPTS_PER_MODEL):
                try:
                    response = call(name, stem, kind)
                except Exception as exc:  # 503/429 and similar: retry, then try the next model
                    last_error = exc
                    log.warning("Gemini %s attempt %d failed: %s", name, attempt + 1, exc)
                    if attempt + 1 < ATTEMPTS_PER_MODEL:
                        sleep(RETRY_DELAY_SECONDS)
                    continue
                if not response.text:
                    raise ValueError("empty Gemini response")
                return parse_sidecar("gemini.json", response.text)
        assert last_error is not None
        raise last_error

    return generate
