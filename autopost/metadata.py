"""Build YouTube metadata: sidecar file first, then generator (Gemini), then config defaults."""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional, Sequence

from autopost.config import Config
from autopost.models import DriveFile, Metadata

log = logging.getLogger(__name__)

TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_MAX = 500
SHORTS_TAG = "#Shorts"
FIELDS = ("title", "description", "tags")

# (file stem, kind) -> dict with any of title/description/tags
Generator = Callable[[str, str], dict]


def parse_sidecar(name: str, text: str) -> dict:
    """Parse a .json or .txt sidecar. Raises ValueError on malformed JSON."""
    if name.lower().endswith(".json"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("sidecar JSON must be an object")
        out: dict = {}
        for key in ("title", "description"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                out[key] = value.strip()
        tags = data.get("tags")
        if isinstance(tags, list):
            clean = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
            if clean:
                out["tags"] = clean
        return out

    lines = text.strip().splitlines()
    if not lines:
        return {}
    out = {"title": lines[0].strip()}
    description = "\n".join(lines[1:]).strip()
    if description:
        out["description"] = description
    return out


_HASHTAG = re.compile(r"#(\w+)")
DESCRIPTION_HASHTAGS_MAX = 15  # YouTube ignores ALL hashtags in a description that has more than 15


def parse_hashtags(text: str) -> list[str]:
    """Every #tag in the text, first occurrence wins, case-insensitive. Other lines are ignored."""
    seen: set[str] = set()
    out: list[str] = []
    for word in _HASHTAG.findall(text.replace("\\#", "#")):
        if word.lower() not in seen:
            seen.add(word.lower())
            out.append(f"#{word}")
    return out


def _append_hashtags(description: str, hashtags: list[str]) -> str:
    present = {tag.lower() for tag in parse_hashtags(description)}
    room = max(0, DESCRIPTION_HASHTAGS_MAX - len(present))
    new = [tag for tag in hashtags if tag.lower() not in present][:room]
    if not new:
        return description
    return f"{description}\n\n{' '.join(new)}".strip()


def pick_sidecar(files: list[DriveFile]) -> Optional[DriveFile]:
    for ext in (".json", ".txt"):
        for file in files:
            if file.name.lower().endswith(ext):
                return file
    return None


def clean_title(stem: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-.]+", " ", stem)).strip()


def fallback(stem: str, cfg: Config) -> dict:
    return {
        "title": clean_title(stem) or "Untitled",
        "description": cfg.default_description,
        "tags": list(cfg.default_tags),
    }


def _strip_angles(text: str) -> str:
    # YouTube rejects < and > in titles and descriptions
    return text.replace("<", "").replace(">", "")


def _fit_tags(tags: list[str]) -> tuple[str, ...]:
    kept: list[str] = []
    used = 0
    for raw in tags:
        tag = _strip_angles(raw).strip()
        if not tag or tag in kept:
            continue
        # YouTube counts quotes around multi-word tags and commas between tags
        cost = len(tag) + (2 if " " in tag else 0) + (1 if kept else 0)
        if used + cost > TAGS_MAX:
            break
        kept.append(tag)
        used += cost
    return tuple(kept)


def _truncate_bytes(text: str, limit: int) -> str:
    # YouTube's description limit is in UTF-8 bytes; "ignore" drops a split trailing character
    return text.encode("utf-8")[:limit].decode("utf-8", "ignore")


def finalize(meta: dict, kind: str, hashtags: Sequence[str] = ()) -> Metadata:
    title = _strip_angles(meta["title"]).strip()[:TITLE_MAX].strip() or "Untitled"
    description = _append_hashtags(_strip_angles(meta["description"]).strip(), list(hashtags))
    if kind == "short" and SHORTS_TAG.lower() not in description.lower():
        room = DESCRIPTION_MAX - len(("\n\n" + SHORTS_TAG).encode("utf-8"))
        description = f"{_truncate_bytes(description, room)}\n\n{SHORTS_TAG}".strip()
    return Metadata(
        title=title,
        description=_truncate_bytes(description, DESCRIPTION_MAX),
        tags=_fit_tags(list(meta["tags"]) + [tag.lstrip("#") for tag in hashtags]),
    )


def build_metadata(
    stem: str,
    kind: str,
    sidecar: Optional[tuple[str, str]],
    generate: Optional[Generator],
    cfg: Config,
    hashtags: Sequence[str] = (),
) -> Metadata:
    """sidecar is (file name, file text) or None. hashtags are appended to every description."""
    meta: dict = {}
    if sidecar is not None:
        name, text = sidecar
        try:
            meta = parse_sidecar(name, text)
        except ValueError as exc:
            log.warning("ignoring malformed sidecar %s: %s", name, exc)

    missing = [key for key in FIELDS if key not in meta]
    if missing and generate is not None:
        try:
            generated = generate(stem, kind)
            for key in missing:
                if key in generated:
                    meta[key] = generated[key]
        except Exception as exc:  # any AI failure must not block the upload
            log.warning("metadata generator failed for %s: %s", stem, exc)

    defaults = fallback(stem, cfg)
    for key in FIELDS:
        meta.setdefault(key, defaults[key])
    return finalize(meta, kind, hashtags)
