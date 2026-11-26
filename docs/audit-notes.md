# YouTube API audit: answers to paste

**Form:** https://support.google.com/youtube/contact/yt_api_form
**Request type:** "Complete a compliance audit to request for additional quota" (the first-audit path). Request no extra quota; the goal is to lift the private-only restriction on uploads.

**App name:** Autopost

**Who runs it:** A developer operates the tool on behalf of one YouTube channel owner, with the owner's consent. The Google Cloud project belongs to the developer; the OAuth authorization was granted by the channel owner's own Google account.

**What does your app do?**
Autopost is a single-channel, internal automation tool. Once a day it takes video files that the channel owner placed in their own Google Drive folder and uploads them to the owner's own YouTube channel with `videos.insert`, scheduled for a fixed time of day with `status.publishAt`. Titles, descriptions and tags come from a text file next to each video, or are drafted from the file name using the Google Gemini API. Hashtags come from a text file the owner keeps in the same folder. It runs as a scheduled GitHub Actions job.

**Who are the users?** One channel owner. No other users, no public sign-up, no UI for third parties.

**Which API methods?** YouTube: `videos.insert` (part=snippet,status) only. Drive: read-only listing and download of the owner's folder (`drive.readonly`). No reads of other channels' data, no analytics, no comments.

**Data storage:** No YouTube data is stored except the IDs of the uploaded videos, kept in a log file in the tool's repository to prevent duplicate uploads. Video files are deleted from the job's temporary disk right after upload. OAuth credentials are stored only as encrypted GitHub Actions secrets.

**Home page:** https://bayezid-hossain.github.io/
**Privacy policy URL:** https://bayezid-hossain.github.io/autopost-policy/privacy-policy.html
**Terms URL:** https://bayezid-hossain.github.io/autopost-policy/terms.html
**Source code (public):** https://github.com/bayezid-hossain/youtube-autopost

**Quota needed:** The default 10,000 units/day is enough (at most 3–6 uploads per day). We request the audit only to lift the private-only restriction that applies to uploads from unverified API projects, so scheduled videos can publish automatically.
