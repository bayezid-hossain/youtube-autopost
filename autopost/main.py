"""One autopost run: plan today's slots, upload, record, move, summarize."""
from __future__ import annotations

import argparse
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from autopost.auth import MissingSecret, credentials_from_env
from autopost.config import Config, load_config
from autopost.drive import Drive, split_listing
from autopost.ledger import Ledger
from autopost.metadata import Generator, build_metadata, parse_hashtags, pick_sidecar
from autopost.models import DriveFile, Job
from autopost.notify import send_telegram, write_step_summary
from autopost.scheduler import plan_day, project_queue
from autopost.youtube import QuotaExceeded, build_body, upload

log = logging.getLogger("autopost")
KINDS = ("video", "short")

Uploader = Callable[[Path, dict], str]


@dataclass
class RunResult:
    planned: list[Job] = field(default_factory=list)
    uploaded: list[tuple[Job, str]] = field(default_factory=list)
    failed: list[tuple[Job, str]] = field(default_factory=list)
    quota_hit: bool = False
    queue_left: dict[str, int] = field(default_factory=dict)
    remaining: dict[str, list[DriveFile]] = field(default_factory=dict)


def _stem(file: DriveFile) -> str:
    return os.path.splitext(file.name)[0]


def _queue_folder(cfg: Config, kind: str) -> Optional[str]:
    return cfg.queue_videos_folder_id if kind == "video" else cfg.queue_shorts_folder_id


def _move_with_sidecars(drive, video: DriveFile, sidecars: list[DriveFile], src: str, dst: Optional[str]) -> None:
    if dst is None:  # no posted folder configured: the ledger alone prevents re-uploads
        return
    for file in [video, *sidecars]:
        drive.move(file.id, src, dst)


def _load_hashtags(drive, cfg: Config, listings: list[list[DriveFile]]) -> list[str]:
    if not cfg.hashtags_file:
        return []
    for files in listings:
        for file in files:
            if file.name == cfg.hashtags_file:
                try:
                    return parse_hashtags(drive.read_text(file.id))
                except Exception as exc:
                    log.warning("could not read hashtags file %s: %s", file.name, exc)
                    return []
    log.warning("hashtags file %s not found in the queue folder(s)", cfg.hashtags_file)
    return []


def _read_sidecar(drive, files: list[DriveFile]) -> Optional[tuple[str, str]]:
    chosen = pick_sidecar(files)
    if chosen is None:
        return None
    try:
        return chosen.name, drive.read_text(chosen.id)
    except Exception as exc:
        log.warning("could not read sidecar %s: %s", chosen.name, exc)
        return None


def _remove_quietly(path: Path) -> None:
    """Delete a temp file; on Windows the upload may still hold it open, which must not mask the real error."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("could not delete temp file %s: %s", path, exc)


def run(
    cfg: Config,
    drive,
    uploader: Uploader,
    ledger: Ledger,
    generate: Optional[Generator],
    now: datetime,
    dry_run: bool,
    workdir: Path,
) -> RunResult:
    pending: dict[str, list[DriveFile]] = {}
    sidecars: dict[str, dict[str, list[DriveFile]]] = {}
    listings: list[list[DriveFile]] = []
    for kind in KINDS:
        folder = _queue_folder(cfg, kind)
        pending[kind] = []
        sidecars[kind] = {}
        if folder is None:
            continue
        listing = drive.list_folder(folder)
        listings.append(listing)
        videos, sidecars[kind] = split_listing(listing)
        for video in videos:
            if not ledger.has(video.id):
                pending[kind].append(video)
                continue
            if dry_run or cfg.posted_folder_id is None:
                continue
            # uploaded on an earlier run but the move failed: retry the move only
            try:
                _move_with_sidecars(drive, video, sidecars[kind].get(_stem(video), []), folder, cfg.posted_folder_id)
            except Exception as exc:
                log.warning("could not move already-posted %s: %s", video.name, exc)

    hashtags = _load_hashtags(drive, cfg, listings)
    today = now.astimezone(cfg.timezone).date()
    result = RunResult(planned=plan_day(today, now, cfg, pending["video"], pending["short"]))

    for job in result.planned:
        stem = _stem(job.file)
        folder = _queue_folder(cfg, job.kind)
        side_files = sidecars[job.kind].get(stem, [])
        meta = build_metadata(stem, job.kind, _read_sidecar(drive, side_files), generate, cfg, hashtags)
        if dry_run:
            log.info("[dry-run] %s %s at %s -> %r", job.kind, job.file.name, job.publish_at.isoformat(), meta.title)
            continue

        path = workdir / f"{job.file.id}{Path(job.file.name).suffix}"
        try:
            drive.download(job.file.id, path)
            video_id = uploader(path, build_body(meta, cfg, job.publish_at))
        except QuotaExceeded as exc:
            log.warning("YouTube quota reached, stopping: %s", exc)
            result.quota_hit = True
            break
        except Exception as exc:
            log.error("failed %s: %s", job.file.name, exc)
            result.failed.append((job, str(exc)))
            continue
        finally:
            _remove_quietly(path)

        try:
            ledger.add(job.file.id, video_id, job.publish_at, datetime.now(timezone.utc))
        except Exception as exc:
            log.error(
                "uploaded %s as YouTube video %s but ledger write failed: %s; stopping to avoid duplicates",
                job.file.name,
                video_id,
                exc,
            )
            result.failed.append((job, f"uploaded as {video_id} but ledger write failed: {exc}"))
            break
        result.uploaded.append((job, video_id))
        log.info("uploaded %s %s -> %s", job.kind, job.file.name, video_id)
        try:
            _move_with_sidecars(drive, job.file, side_files, folder, cfg.posted_folder_id)
        except Exception as exc:
            log.warning("uploaded %s but move failed (retried next run): %s", job.file.name, exc)

    done = {kind: sum(1 for job, _ in result.uploaded if job.kind == kind) for kind in KINDS}
    result.queue_left = {kind: len(pending[kind]) - done[kind] for kind in KINDS}
    uploaded_ids = {job.file.id for job, _ in result.uploaded}
    result.remaining = {kind: [f for f in pending[kind] if f.id not in uploaded_ids] for kind in KINDS}
    return result


def format_queue(result: RunResult, cfg: Config, now: datetime, dry_run: bool) -> str:
    """Markdown list of every queued file with its expected publish time (first come, first served)."""
    today = now.astimezone(cfg.timezone).date()
    # a real run has used today's remaining slots, so the rest of the queue starts tomorrow
    start = today if dry_run or not result.planned else today + timedelta(days=1)
    jobs = project_queue(start, now, cfg, result.remaining.get("video", []), result.remaining.get("short", []))
    scheduled = {job.file.id: job for job in jobs}
    lines = [
        "# Upload queue",
        "",
        f"Updated {now.astimezone(cfg.timezone):%Y-%m-%d %H:%M} ({cfg.timezone.key}). "
        "Order: Drive upload time, first come first served. Times are estimates.",
        "",
        "| # | File | Added to Drive | Expected publish |",
        "|---|---|---|---|",
    ]
    files = result.remaining.get("video", []) + result.remaining.get("short", [])
    files.sort(key=lambda f: scheduled[f.id].publish_at if f.id in scheduled else datetime.max.replace(tzinfo=timezone.utc))
    for i, file in enumerate(files, 1):
        added = _local(file.created_time, cfg)
        job = scheduled.get(file.id)
        when = f"{job.publish_at.astimezone(cfg.timezone):%Y-%m-%d %H:%M}" if job else "no slot configured"
        name = file.name.replace("|", "\\|")
        lines.append(f"| {i} | {name} | {added} | {when} |")
    if not files:
        lines.append("| - | Queue empty: add videos to the Drive folder. | | |")
    return "\n".join(lines) + "\n"


def _local(rfc3339: str, cfg: Config) -> str:
    try:
        return f"{datetime.fromisoformat(rfc3339.replace('Z', '+00:00')).astimezone(cfg.timezone):%Y-%m-%d %H:%M}"
    except ValueError:
        return rfc3339 or "?"


def format_summary(result: RunResult, dry_run: bool) -> str:
    head = "autopost dry run" if dry_run else "autopost run"
    lines = [
        f"{head}: {len(result.uploaded)} uploaded, {len(result.failed)} failed, {len(result.planned)} planned"
    ]
    for job, video_id in result.uploaded:
        lines.append(f"- uploaded {job.kind} {job.file.name} -> https://youtu.be/{video_id}")
    for job, error in result.failed:
        lines.append(f"- FAILED {job.kind} {job.file.name}: {error}")
    if result.quota_hit:
        lines.append("- stopped: YouTube daily quota reached")
    if dry_run:
        for job in result.planned:
            lines.append(f"- would upload {job.kind} {job.file.name} at {job.publish_at:%Y-%m-%d %H:%M} UTC")
    left = result.queue_left
    lines.append(f"Queue left: {left.get('video', 0)} videos, {left.get('short', 0)} shorts")
    if not any(left.values()):
        lines.append("Queue empty: add more files to Drive.")
    return "\n".join(lines)


def _make_generator(cfg: Config) -> Optional[Generator]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        log.warning("GEMINI_API_KEY not set: using fallback metadata")
        return None
    from google import genai

    from autopost.gemini import make_gemini

    return make_gemini(genai.Client(api_key=key), cfg.gemini_model, cfg.default_description)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="autopost", description="Upload queued Google Drive videos to YouTube.")
    parser.add_argument("--dry-run", action="store_true", help="plan and generate metadata only; upload nothing")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--ledger", default="posted_log.json", help="path to posted_log.json")
    parser.add_argument("--queue-file", default="QUEUE.md", help="where to write the upload queue")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        cfg = load_config(args.config)
        folder_ids = (cfg.queue_videos_folder_id, cfg.queue_shorts_folder_id, cfg.posted_folder_id)
        if any(folder_id and folder_id.startswith("REPLACE_WITH_") for folder_id in folder_ids):
            log.error("config.yaml still has placeholder Drive folder IDs; set drive.* to your real folder IDs")
            return 1
        creds = credentials_from_env()
        drive = Drive(build("drive", "v3", credentials=creds, cache_discovery=False))
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        with tempfile.TemporaryDirectory() as tmp:
            started = datetime.now(timezone.utc)
            result = run(
                cfg,
                drive,
                lambda path, body: upload(youtube, path, body),
                Ledger(args.ledger),
                _make_generator(cfg),
                started,
                args.dry_run,
                Path(tmp),
            )
    except MissingSecret as exc:
        log.error("%s. Add them as GitHub repository secrets.", exc)
        return 1
    except RefreshError as exc:
        log.error(
            "Google auth failed (%s). Re-run auth_setup.py and update the GOOGLE_REFRESH_TOKEN secret.", exc
        )
        return 1
    except HttpError as exc:
        log.error("Google API error: %s. If this is a 404, check the drive.* folder IDs in config.yaml.", exc)
        return 1
    except (ValueError, OSError) as exc:
        log.error("%s", exc)
        return 1

    try:
        Path(args.queue_file).write_text(format_queue(result, cfg, started, args.dry_run), encoding="utf-8")
    except OSError as exc:
        log.warning("could not write %s: %s", args.queue_file, exc)

    text = format_summary(result, args.dry_run)
    print(text)
    write_step_summary(text)
    send_telegram(text)
    return 1 if result.failed else 0
