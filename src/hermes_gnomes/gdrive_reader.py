"""Google Drive reader for product photo sync.

Phase 0 defines:
- A DriveClient protocol (for test injection).
- A real GoogleDriveClient that wraps google-api-python-client (imported lazily).
- A GDriveReader that syncs a shared folder into a local images/ directory
  and records metadata in customer_db.image_assets.

The live smoke test against a real folder is a manual post-plan step documented
in the README.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

IMAGE_MIMETYPE_PREFIX = "image/"


@dataclass
class ListedFile:
    id: str
    filename: str
    mime_type: str
    bytes_size: int


class DriveClient(Protocol):
    def list_files_in_folder(self, folder_id: str) -> list[dict]: ...
    def download_file(self, file_id: str) -> bytes: ...


class GoogleDriveClient:
    """Real google-api-python-client wrapper. Imported only when used."""

    def __init__(self, service_account_json_path: str) -> None:
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore

        creds = service_account.Credentials.from_service_account_file(
            service_account_json_path,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_files_in_folder(self, folder_id: str) -> list[dict]:
        query = f"'{folder_id}' in parents and trashed = false"
        fields = "files(id, name, mimeType, size)"
        resp = self._service.files().list(q=query, fields=fields, pageSize=1000).execute()
        return resp.get("files", [])

    def download_file(self, file_id: str) -> bytes:
        return self._service.files().get_media(fileId=file_id).execute()


class GDriveReader:
    def __init__(
        self,
        *,
        drive_client: DriveClient,
        folder_id: str,
        local_dir: Path,
        db_path: Path,
    ) -> None:
        self.drive_client = drive_client
        self.folder_id = folder_id
        self.local_dir = local_dir
        self.db_path = db_path
        self.local_dir.mkdir(parents=True, exist_ok=True)

    def sync_folder(self) -> list[ListedFile]:
        """Download new files from the configured folder and record metadata.

        Idempotent: files already recorded (by external_id) are skipped.
        Returns the list of files newly synced this run.
        """
        remote_files = self.drive_client.list_files_in_folder(self.folder_id)
        synced: list[ListedFile] = []

        for f in remote_files:
            mime = f.get("mimeType", "")
            if not mime.startswith(IMAGE_MIMETYPE_PREFIX):
                continue

            gid = f["id"]
            if self._already_recorded(gid):
                continue

            content = self.drive_client.download_file(gid)
            sha = hashlib.sha256(content).hexdigest()
            filename = f["name"]
            local_path = self.local_dir / filename
            local_path.write_bytes(content)

            self._record_asset(
                gid=gid,
                filename=filename,
                local_path=local_path,
                sha256=sha,
                bytes_size=len(content),
            )
            synced.append(
                ListedFile(
                    id=gid,
                    filename=filename,
                    mime_type=mime,
                    bytes_size=len(content),
                )
            )
        return synced

    def _already_recorded(self, external_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM image_assets WHERE source = 'gdrive' AND external_id = ?",
                (external_id,),
            ).fetchone()
        return row is not None

    def _record_asset(
        self,
        *,
        gid: str,
        filename: str,
        local_path: Path,
        sha256: str,
        bytes_size: int,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO image_assets
                    (source, external_id, local_path, filename, sha256, bytes, fetched_at)
                VALUES ('gdrive', ?, ?, ?, ?, ?, ?)
                """,
                (gid, str(local_path), filename, sha256, bytes_size, now),
            )
            conn.commit()
