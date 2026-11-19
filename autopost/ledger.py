"""posted_log.json: record of every successful upload, used to prevent duplicates."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{self.path} is corrupted: invalid JSON ({exc})") from exc
            if not isinstance(loaded, list):
                raise ValueError(f"{self.path} is corrupted: expected a JSON list of entries")
            self.entries: list[dict] = loaded
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
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.entries, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
