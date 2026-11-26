# YouTube API audit: answers to paste

**Form:** YouTube API Services – Audit and Quota Extension Form (linked from the YouTube Data API docs, "Quota and Compliance Audits").

**App name:** Autopost

**What does your app do?**
Autopost is a single-user, internal tool. Each day it takes video files that I (the channel owner) placed in my own Google Drive folder and uploads them to my own YouTube channel with `videos.insert`, scheduled with `status.publishAt`. Titles, descriptions and tags come from a text file I write next to each video, or are drafted from the file name using the Google Gemini API. It runs as a scheduled GitHub Actions job in my private repository.

**Who are the users?** Only me, the channel owner. No other users, no public sign-up.

**Which API methods?** `videos.insert` (part=snippet,status). No reads of other channels' data.

**Data storage:** No YouTube data is stored except the IDs of my own uploaded videos, kept in a log file in my private repository to prevent duplicate uploads.

**Privacy policy URL:** https://bayezid-hossain.github.io/autopost-policy/privacy-policy.html
**Terms URL:** https://bayezid-hossain.github.io/autopost-policy/terms.html

**Quota needed:** Default 10,000 units/day is enough (max 6 uploads/day). Requesting audit only to lift the private-only restriction on uploads from an unverified project.
