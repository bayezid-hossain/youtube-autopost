"""Google Drive access: list queue folders, stream downloads, move files."""
from __future__ import annotations

import os
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload

from autopost.models import DriveFile

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"})
SIDECAR_EXTENSIONS = frozenset({".json", ".txt"})
DOWNLOAD_CHUNK = 50 * 1024 * 1024
RETRIES = 3  # googleapiclient retries with exponential backoff


def split_listing(
    files: list[DriveFile],
) -> tuple[list[DriveFile], dict[str, list[DriveFile]]]:
    """Return (videos oldest first, sidecars grouped by file stem). Other files are ignored."""
    videos: list[DriveFile] = []
    sidecars: dict[str, list[DriveFile]] = {}
    for file in files:
        stem, ext = os.path.splitext(file.name)
        ext = ext.lower()
        if ext in VIDEO_EXTENSIONS:
            videos.append(file)
        elif ext in SIDECAR_EXTENSIONS:
            sidecars.setdefault(stem, []).append(file)
    videos.sort(key=lambda v: (v.created_time, v.name))
    return videos, sidecars


class Drive:
    def __init__(self, service):
        self._service = service

    def list_folder(self, folder_id: str) -> list[DriveFile]:
        files: list[DriveFile] = []
        page_token = None
        while True:
            response = (
                self._service.files()
                .list(
                    q=(
                        f"'{folder_id}' in parents and trashed = false"
                        " and mimeType != 'application/vnd.google-apps.folder'"
                    ),
                    fields="nextPageToken, files(id, name, createdTime)",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute(num_retries=RETRIES)
            )
            files.extend(
                DriveFile(id=item["id"], name=item["name"], created_time=item["createdTime"])
                for item in response.get("files", [])
            )
            page_token = response.get("nextPageToken")
            if not page_token:
                return files

    def download(self, file_id: str, dest: Path) -> None:
        request = self._service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with open(dest, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=DOWNLOAD_CHUNK)
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=RETRIES)

    def read_text(self, file_id: str) -> str:
        data = (
            self._service.files()
            .get_media(fileId=file_id, supportsAllDrives=True)
            .execute(num_retries=RETRIES)
        )
        return data.decode("utf-8-sig")

    def move(self, file_id: str, from_folder_id: str, to_folder_id: str) -> None:
        self._service.files().update(
            fileId=file_id,
            addParents=to_folder_id,
            removeParents=from_folder_id,
            fields="id",
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)
