import hashlib
import sqlite3
from pathlib import Path

from hermes_gnomes.customer_db import init_db
from hermes_gnomes.gdrive_reader import GDriveReader


class FakeDriveClient:
    def __init__(self, files: list[dict], content_map: dict[str, bytes]) -> None:
        self._files = files
        self._content_map = content_map

    def list_files_in_folder(self, folder_id: str) -> list[dict]:
        return list(self._files)

    def download_file(self, file_id: str) -> bytes:
        return self._content_map[file_id]


def test_sync_new_files_downloads_and_records(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    init_db(db_path)

    image_dir = tmp_path / "images"
    image_dir.mkdir()

    content1 = b"fake jpeg bytes one"
    content2 = b"fake jpeg bytes two"
    fake = FakeDriveClient(
        files=[
            {
                "id": "g1",
                "name": "gnome_red.jpg",
                "mimeType": "image/jpeg",
                "size": str(len(content1)),
            },
            {
                "id": "g2",
                "name": "gnome_blue.jpg",
                "mimeType": "image/jpeg",
                "size": str(len(content2)),
            },
        ],
        content_map={"g1": content1, "g2": content2},
    )

    reader = GDriveReader(
        drive_client=fake,
        folder_id="test-folder",
        local_dir=image_dir,
        db_path=db_path,
    )
    synced = reader.sync_folder()

    assert len(synced) == 2
    assert (image_dir / "gnome_red.jpg").read_bytes() == content1
    assert (image_dir / "gnome_blue.jpg").read_bytes() == content2

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT filename, sha256, bytes FROM image_assets").fetchall()
    conn.close()
    assert len(rows) == 2
    shas = {r[1] for r in rows}
    assert hashlib.sha256(content1).hexdigest() in shas
    assert hashlib.sha256(content2).hexdigest() in shas


def test_sync_is_idempotent_on_same_file(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    init_db(db_path)
    image_dir = tmp_path / "images"
    image_dir.mkdir()

    content = b"same bytes every time"
    fake = FakeDriveClient(
        files=[
            {"id": "g1", "name": "stable.jpg", "mimeType": "image/jpeg", "size": str(len(content))}
        ],
        content_map={"g1": content},
    )
    reader = GDriveReader(
        drive_client=fake,
        folder_id="f",
        local_dir=image_dir,
        db_path=db_path,
    )
    reader.sync_folder()
    reader.sync_folder()
    reader.sync_folder()

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM image_assets").fetchone()[0]
    conn.close()
    assert count == 1


def test_sync_skips_non_image_mimetypes(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    init_db(db_path)
    image_dir = tmp_path / "images"
    image_dir.mkdir()

    fake = FakeDriveClient(
        files=[
            {"id": "d1", "name": "spec.pdf", "mimeType": "application/pdf", "size": "10"},
            {"id": "i1", "name": "ok.jpg", "mimeType": "image/jpeg", "size": "5"},
        ],
        content_map={"d1": b"pdfbytes", "i1": b"jpgbt"},
    )
    reader = GDriveReader(
        drive_client=fake,
        folder_id="f",
        local_dir=image_dir,
        db_path=db_path,
    )
    synced = reader.sync_folder()

    assert len(synced) == 1
    assert synced[0].filename == "ok.jpg"
    assert not (image_dir / "spec.pdf").exists()
