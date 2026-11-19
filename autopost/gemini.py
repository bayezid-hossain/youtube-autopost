"""Gemini (free tier) metadata generator. Sees only the file name, never the video."""
from __future__ import annotations

from autopost.metadata import Generator, parse_sidecar

PROMPT = """You write metadata for a YouTube {label}.
Base it only on the file name below. Do not invent specific facts the file name does not suggest.
Return only JSON with these keys:
- "title": catchy, max 90 characters, no all-caps clickbait
- "description": 2-4 short paragraphs, max 1500 characters
- "tags": list of 8-15 short search tags

File name: {stem}
Channel description: {context}
"""

LABELS = {"video": "video", "short": "Short (vertical, under 3 minutes)"}


def make_gemini(client, model: str, context: str) -> Generator:
    """client is a google.genai.Client (or a test fake with the same .models API)."""

    def generate(stem: str, kind: str) -> dict:
        response = client.models.generate_content(
            model=model,
            contents=PROMPT.format(label=LABELS[kind], stem=stem, context=context or "(none)"),
            config={"response_mime_type": "application/json"},
        )
        return parse_sidecar("gemini.json", response.text)

    return generate
