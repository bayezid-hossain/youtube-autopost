# Autopost: Google Drive → YouTube, on a schedule, for free

Every morning a GitHub Actions job takes the next files from your Drive queue folders and uploads them to YouTube for today's time slots (max 6 per day).

- `queue/videos/` → regular videos, `queue/shorts/` → Shorts
- Optional sidecar next to a video: `my-video.json` (`{"title": ..., "description": ..., "tags": [...]}`) or `my-video.txt` (line 1 = title, rest = description). Missing fields are written by Gemini from the file name; if Gemini fails, defaults from `config.yaml` are used.
- After upload, the video and its sidecar move to `posted/`. `posted_log.json` prevents duplicates.

## Modes

| `publish_mode` | What happens | When to use |
|---|---|---|
| `private` | All of today's uploads happen at the 06:00 run, as private videos with metadata filled in. You publish them in YouTube Studio. | Until the YouTube API audit is approved |
| `scheduled` | Same, plus YouTube auto-publishes each video at its slot time (`publishAt`). | After audit approval |

## One-time setup (≈45 min, all free)

1. **Google Cloud project:** at https://console.cloud.google.com create a project. Under *APIs & Services → Library*, enable **YouTube Data API v3** and **Google Drive API**.
2. **OAuth consent screen:** User type *External*. Add scopes `.../auth/youtube.upload` and `.../auth/drive`. Add your channel's Google account as a test user. Then click **Publish app** so the status is **In production** (otherwise the token expires every 7 days). You will see an "unverified app" warning when signing in; click *Advanced → Go to app*. That's fine for a single-user tool.
3. **OAuth client:** *Credentials → Create credentials → OAuth client ID → Desktop app*. Download the JSON as `client_secret.json` into this folder (it's gitignored).
4. **Refresh token:**
   ```powershell
   python -m venv .venv; .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python auth_setup.py client_secret.json
   ```
   Sign in with the **channel's** Google account. Copy the three printed values.
5. **Gemini key:** https://aistudio.google.com → *Get API key* (free tier).
6. **Drive folders:** create `autopost/queue/videos`, `autopost/queue/shorts`, `autopost/posted`. Open each and copy the ID from the URL (`drive.google.com/drive/folders/<ID>`) into `config.yaml`. Set `timezone` and `slots` there too.
7. **Cron time:** in `.github/workflows/autopost.yml` set the cron to 06:00 *your* time in UTC. Examples: Asia/Dhaka `0 0 * * *`, Asia/Kolkata `30 0 * * *`, Europe/London (winter) `0 6 * * *`, America/New_York (winter) `0 11 * * *`.
8. **GitHub:** create a **private** repo, push this folder, then add secrets under *Settings → Secrets and variables → Actions*: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `GEMINI_API_KEY`. Optional: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (create a bot with @BotFather; get your chat ID from @userinfobot).
9. **Test:** *Actions → autopost → Run workflow* with **dry_run** ticked. Check the plan in the job summary. Then put one small test video in `queue/shorts`, run again without dry run, and confirm: private video in Studio, metadata filled in, file moved to `posted/`, new commit updating `posted_log.json`.

## API audit (to auto-publish)

GitHub Pages is free only for **public** repos, so host the policy pages separately:
1. Replace `CONTACT_EMAIL` in `docs/policy/privacy-policy.md` and `docs/policy/terms.md` with your contact email.
2. Create a new **public** repo (e.g. `autopost-policy`), copy both files into it, enable *Settings → Pages* (branch `main`, root).
3. Fill in the YouTube API audit form using `docs/audit-notes.md`, with your Pages URLs.
4. After approval: set `publish_mode: scheduled` in `config.yaml` and push.

## Limits and costs

- YouTube API: 10,000 units/day free ≈ 6 uploads. `daily_cap` enforces it.
- GitHub Actions private repo: 2,000 free minutes/month; one run ≈ 2–10 min depending on file sizes.
- Gemini: free tier; one short request per video.
- Runner disk ≈ 14 GB free; each video is deleted right after upload.
- YouTube description limit: 5,000 bytes (Bengali and other non-Latin scripts use ~3 bytes per character; autopost trims automatically).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Run fails with "Google auth failed" | Run `python auth_setup.py client_secret.json` again and update `GOOGLE_REFRESH_TOKEN`. Check the consent screen is *In production*. |
| "stopped: YouTube daily quota reached" | Normal if many uploads failed and retried; leftovers go tomorrow. |
| Uploaded videos stuck private | Expected until the API audit is approved. |
| Slot error in config | Times must be quoted (`"18:00"`) and later than 06:30. |
| Nothing uploads, "Queue empty" | Add files to `queue/videos` or `queue/shorts`. |
| Run fails with `posted_log.json is corrupted` | Fix or restore the file from git history (`git log -p posted_log.json`); it must be a JSON list. |

## Development

```powershell
python -m pytest -v
python -m autopost --dry-run   # needs the GOOGLE_* env vars set locally
```
