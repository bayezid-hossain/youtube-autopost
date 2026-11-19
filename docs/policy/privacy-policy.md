# Privacy Policy: Autopost

_Last updated: 2026-11-19_

Autopost is a personal tool that uploads videos from the owner's Google Drive to the owner's own YouTube channel. It has one user: the channel owner.

## What data it uses
- **Google account access (OAuth):** permission to read and move files in Google Drive and to upload videos to YouTube. The OAuth refresh token and client credentials are stored only as encrypted GitHub Actions secrets in the owner's private repository.
- **Video files:** downloaded from Drive to a temporary GitHub Actions runner, uploaded to YouTube, then deleted from the runner when the run ends.
- **File names:** sent to the Google Gemini API to draft titles, descriptions and tags.
- **Upload log:** Drive file IDs and YouTube video IDs are kept in the owner's private repository to prevent duplicate uploads.

## What it does not do
- It does not collect data from anyone other than the owner.
- It does not sell, share or transfer data to third parties.
- It does not use YouTube data for advertising or analytics.

## YouTube API Services
Autopost uses YouTube API Services. By using it you agree to the [YouTube Terms of Service](https://www.youtube.com/t/terms). See also the [Google Privacy Policy](https://policies.google.com/privacy).

You can revoke Autopost's access at any time at [Google security settings](https://myaccount.google.com/permissions).

## Contact
CONTACT_EMAIL
