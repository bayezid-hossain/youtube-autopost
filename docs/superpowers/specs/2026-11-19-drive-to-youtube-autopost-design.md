# Drive → YouTube Autopost — Design

**Date:** 2026-11-19
**Status:** Approved in brainstorming, pending spec review

## Goal

Automatically take videos from a Google Drive queue and upload them to one YouTube channel on a fixed daily schedule — regular videos and Shorts — using only free services.

## Constraints

- **Zero cost.** Every service must be on a free tier: GitHub Actions (private repo, 2,000 min/month), YouTube Data API v3, Google Drive API, Gemini API free tier, optional Telegram bot.
- **YouTube API quota:** 10,000 units/day per project; one upload ≈ 1,600 units → hard cap of **6 uploads/day** (enforced by config `daily_cap`, max 6).
- **Unverified API project:** uploads are locked to private until the project passes the YouTube API compliance audit. The system runs in `private` mode until approval, then switches to `scheduled` mode via one config value. No code change.
- **OAuth consent screen must be "In production"** so the refresh token does not expire every 7 days.
- No LLM handles video bytes. Video transfer is plain code (Drive download stream → YouTube resumable upload). The LLM only generates text metadata.

## Decisions

| Topic | Decision |
|---|---|
| Content types | Regular videos + Shorts |
| Video vs Short | Determined by Drive folder: `queue/videos/` or `queue/shorts/` |
| Schedule model | Fixed daily time slots defined in `config.yaml`, ≤ 6 total |
| Metadata | Sidecar file if present (`<name>.json` or `<name>.txt`); otherwise Gemini generates from the file name; otherwise fallback defaults |
| Runner | GitHub Actions cron, once daily at 06:00 in the configured timezone, plus manual `workflow_dispatch` |
| Publishing | `publish_mode: private` (pre-audit) → `publish_mode: scheduled` (post-audit, uses `publishAt`) |
| Post-upload | Move video + sidecar to `posted/` in Drive; record in `posted_log.json` |
| Alerts | GitHub failure email (always); Telegram run summary only if Telegram secrets are set |
| Language | Python 3.12 |

## Architecture

```
GitHub Actions (cron daily 06:00 configured TZ, + manual trigger)
  └─ python -m autopost [--dry-run]
       ├─ config.yaml       timezone, slots, folder IDs, daily_cap, publish_mode, default metadata
       ├─ config.py         load + validate config
       ├─ auth.py           build Google credentials from refresh token in env
       ├─ drive.py          list queue folders (oldest first), stream-download file, move to posted/
       ├─ metadata.py       sidecar → Gemini → fallback; returns {title, description, tags}
       ├─ youtube.py        resumable upload; privacyStatus + optional publishAt
       ├─ scheduler.py      map today's slots → next files per folder, respect daily_cap
       ├─ ledger.py         read/append posted_log.json, duplicate check by Drive file ID
       ├─ notify.py         Telegram summary (no-op if not configured)
       └─ main.py           orchestrates one run, writes GitHub job summary
auth_setup.py              local one-time script: OAuth browser flow → prints refresh token
```

Each module has one job and is tested in isolation with its external API mocked.

### Config (`config.yaml`)

```yaml
timezone: Asia/Dhaka          # any IANA timezone; required
publish_mode: private          # private | scheduled
daily_cap: 6                   # must be 1..6
slots:
  videos: ["18:00"]
  shorts: ["10:00", "13:00", "16:00", "20:00", "22:00"]
drive:
  queue_videos_folder_id: "<id>"
  queue_shorts_folder_id: "<id>"
  posted_folder_id: "<id>"
defaults:
  description: "..."
  tags: ["..."]
  category_id: "22"
```

Validation rejects: total slots > `daily_cap`, `daily_cap` > 6, unknown `publish_mode`, invalid timezone, malformed `HH:MM`, any slot at or before 06:30 local (the daily run starts at 06:00 and needs lead time).

**Cron note:** GitHub Actions cron is UTC. The workflow's cron expression is the UTC equivalent of 06:00 in `timezone` (e.g. Asia/Dhaka → `0 0 * * *`). README documents the conversion.

**Mode note:** In `private` mode, slots only decide *which and how many* files go each day; all of the day's uploads happen during the 06:00 run and land as private drafts. In `scheduled` mode, slots also become each video's `publishAt` time.

### Sidecar format

- `<video-name>.json`: `{"title": str, "description": str, "tags": [str]}`. Any field may be omitted; missing fields are filled by Gemini/fallback.
- `<video-name>.txt`: first line = title, remaining lines = description. Tags come from Gemini/fallback.
- `.json` wins if both exist.

### Gemini metadata

- Input: file name (extension stripped), content type (video/short), channel defaults.
- Output: JSON with title (≤ 100 chars; Shorts get `#Shorts` appended to the description), description (≤ 5,000 chars), tags (total ≤ 500 chars).
- Model: current free-tier Gemini Flash model, set in config as `gemini_model`.

## Data flow (one run)

1. Load and validate config; build credentials.
2. Compute today's slots in the configured timezone. Drop slots already in the past (only relevant for manual runs).
3. For each folder, list files oldest first, excluding sidecars and files whose Drive ID is in `posted_log.json`.
4. Pair slots with files (videos slots ↔ videos queue, shorts slots ↔ shorts queue), capped at `daily_cap`.
5. For each pair, in slot order:
   1. Download the video to the runner's temp dir (streamed, chunked).
   2. Build metadata (sidecar → Gemini → fallback).
   3. Upload: `privacyStatus=private`; if `publish_mode=scheduled`, also set `publishAt=<slot as UTC ISO8601>`.
   4. Append `{drive_file_id, youtube_video_id, slot, uploaded_at}` to `posted_log.json`.
   5. Move video + sidecar to `posted/`.
   6. Delete the temp file.
6. Commit the updated `posted_log.json` back to the repo (workflow step).
7. Write the job summary; send Telegram summary if configured.

`--dry-run` performs steps 1–4 and metadata generation, prints the plan, and makes no uploads, moves, or ledger writes.

## Error handling

| Failure | Behavior |
|---|---|
| Drive download error | 3 retries, exponential backoff; then skip file (stays in queue) |
| Upload interrupted | Resumable upload resumes from last chunk; 3 retries on 5xx |
| `quotaExceeded` (403) | Stop run cleanly; remaining files wait for next run |
| Gemini error / rate limit | Use fallback metadata (title from file name, config defaults) |
| Malformed sidecar | Log warning; fall through to Gemini |
| Auth failure (`invalid_grant`) | Fail run with message "re-run auth_setup.py and update GOOGLE_REFRESH_TOKEN" |
| Upload succeeded, move failed | Ledger already records it → never re-uploaded; move retried next run |
| Empty queue | Exit 0; summary/Telegram says "queue empty" |

Run exits non-zero if any file failed for a reason other than quota or empty queue, so GitHub sends a failure email.

## Secrets (GitHub repo secrets)

- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` (required)
- `GEMINI_API_KEY` (required; missing key → fallback metadata only)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (optional)

OAuth scopes: `https://www.googleapis.com/auth/youtube.upload`, `https://www.googleapis.com/auth/drive`.

## Audit support deliverables

- `docs/privacy-policy.md` and `docs/terms.md`, served via GitHub Pages.
- `docs/audit-notes.md`: app description and use-case text to paste into the YouTube API audit form.

## One-time setup (documented in README)

1. Create Google Cloud project; enable YouTube Data API v3 and Google Drive API.
2. OAuth consent screen: External, status **In production**, the two scopes above.
3. Create OAuth client (Desktop app); download `client_secret.json` (never committed).
4. Run `python auth_setup.py` locally → copy refresh token.
5. Get Gemini API key from Google AI Studio.
6. Create Drive folders `autopost/queue/videos`, `autopost/queue/shorts`, `autopost/posted`; put IDs in `config.yaml`.
7. Create private GitHub repo, push, add secrets.
8. Enable GitHub Pages for `docs/`; submit the YouTube API audit form.
9. After approval: set `publish_mode: scheduled`.

## Testing

- **Unit tests (pytest, all external APIs mocked):** config validation; slot/file pairing incl. daily cap and past slots; sidecar parsing (json, txt, malformed); metadata fallback chain; duplicate skip via ledger; quota stop; `publishAt` only in scheduled mode; timezone → UTC conversion.
- **Dry run:** `python -m autopost --dry-run` against real Drive, no side effects.
- **Live smoke test:** one small video in `queue/shorts`, manual workflow trigger; verify private upload in Studio, metadata filled in, file moved to `posted/`, ledger entry committed.

## Out of scope

- Other platforms (TikTok, Instagram, Facebook).
- Thumbnails, playlists, captions/subtitles.
- Multiple channels.
- Analyzing video content with AI (metadata from file name only).
- Browser automation of YouTube Studio.
