"""posted_log.json: record of every successful upload, used to prevent duplicates."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            self.entries: list[dict] = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.entries = []
        self._ids = {entry["drive_file_id"] for entry in self.entries}

    def has(self, drive_file_id: str) -> bool:
        return drive_file_id in self._ids

    def add(
        self,
        drive_file_id: str,
        youtube_video_id: str,
        publish_at: datetime,
        uploaded_at: datetime,
    ) -> None:
        """Append one entry and write the file immediately, so a later crash keeps it."""
        self.entries.append(
            {
                "drive_file_id": drive_file_id,
                "youtube_video_id": youtube_video_id,
                "publish_at": publish_at.isoformat(),
                "uploaded_at": uploaded_at.isoformat(),
            }
        )
        self._ids.add(drive_file_id)
        self.path.write_text(json.dumps(self.entries, indent=2) + "\n", encoding="utf-8")
