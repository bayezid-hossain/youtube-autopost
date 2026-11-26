---
title: autopost - Privacy Policy
---
# Privacy Policy: autopost

_Last updated: 2026-11-26_

autopost is a private tool that uploads videos from a Google Drive folder to one YouTube channel, with the channel owner's permission. It is not offered to the public.

## YouTube API Services
autopost uses **YouTube API Services**. By using autopost you agree to be bound by the [YouTube Terms of Service](https://www.youtube.com/t/terms). Google's handling of your data is described in the [Google Privacy Policy](http://www.google.com/policies/privacy).

## Data autopost accesses
- **Google account access (OAuth 2.0):** permission to upload videos to the owner's YouTube channel (`youtube.upload`) and read-only access to Google Drive (`drive.readonly`) to read the video folder.
- **Video files and file names** in the owner's Drive folder, and a text file with hashtags in that folder.

## How the data is used
- Video files are uploaded to the owner's own YouTube channel with `videos.insert`. Nothing else is read from YouTube.
- File names are sent to the Google Gemini API to draft video titles and descriptions.
- autopost does not use YouTube or Drive data for advertising, analytics, or any other purpose.

## How the data is stored
- The OAuth refresh token and client credentials are stored only as encrypted GitHub Actions secrets. They are never published.
- Video files are downloaded to a temporary GitHub Actions runner, uploaded, and deleted from the runner when the run ends.
- An upload log keeps only the Drive file ID and the YouTube video ID of each uploaded video, to prevent duplicate uploads. It is stored in the tool's code repository.
- autopost uses no cookies and no tracking.

## Sharing
autopost does not sell, share or transfer data to any third party. It does not collect data from anyone other than the channel owner.

## Revoking access and deleting data
- The owner can revoke autopost's access at any time on the [Google security settings page](https://security.google.com/settings/security/permissions). After that, autopost can no longer access YouTube or Drive.
- To delete stored data, contact the developer (below). The upload log, the stored credentials and any other stored data are deleted within 7 days of the request, or within 7 days of access being revoked.

## Contact
[github.com/bayezid-hossain](https://github.com/bayezid-hossain)
