"""
SQLite-backed GeoTIFF overlay catalog.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
import time
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


ASSET_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class GeoTiffAssetConfig:
    database_file: Path
    asset_directory: Path


class GeoTiffAssetStore:
    """Persist GeoTIFF overlay metadata in SQLite and raster files on disk."""

    def __init__(self, config: GeoTiffAssetConfig):
        self.config = config
        self.database_file = Path(config.database_file)
        self.asset_directory = Path(config.asset_directory)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self.asset_directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS geotiff_assets (
                        asset_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        source_filename TEXT NOT NULL,
                        source_path TEXT NOT NULL,
                        preview_path TEXT NOT NULL,
                        bounds_json TEXT NOT NULL,
                        source_width_px INTEGER NOT NULL,
                        source_height_px INTEGER NOT NULL,
                        preview_width_px INTEGER NOT NULL,
                        preview_height_px INTEGER NOT NULL,
                        source_size_bytes INTEGER NOT NULL,
                        mime_type TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_geotiff_assets_created_at
                    ON geotiff_assets(created_at DESC)
                    """
                )

    def _normalize_name(self, value: Optional[str]) -> str:
        if not value:
            return "geotiff"

        name = Path(value).name.strip()
        if not name:
            return "geotiff"

        cleaned = ASSET_NAME_PATTERN.sub("-", name)
        return cleaned.strip("._-") or "geotiff"

    def _asset_dir(self, asset_id: str) -> Path:
        asset_dir = self.asset_directory / asset_id
        asset_dir.mkdir(parents=True, exist_ok=True)
        return asset_dir

    def _row_to_asset(self, row: sqlite3.Row) -> Dict:
        return {
            "asset_id": row["asset_id"],
            "name": row["name"],
            "source_filename": row["source_filename"],
            "source_path": row["source_path"],
            "preview_path": row["preview_path"],
            "bounds": json.loads(row["bounds_json"]),
            "source_width_px": row["source_width_px"],
            "source_height_px": row["source_height_px"],
            "preview_width_px": row["preview_width_px"],
            "preview_height_px": row["preview_height_px"],
            "source_size_bytes": row["source_size_bytes"],
            "mime_type": row["mime_type"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_assets(self) -> List[Dict]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT asset_id, name, source_filename, source_path, preview_path,
                           bounds_json, source_width_px, source_height_px,
                           preview_width_px, preview_height_px, source_size_bytes,
                           mime_type, created_at, updated_at
                    FROM geotiff_assets
                    ORDER BY created_at DESC
                    """
                ).fetchall()

        return [self._row_to_asset(row) for row in rows]

    def get_asset(self, asset_id: str) -> Optional[Dict]:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT asset_id, name, source_filename, source_path, preview_path,
                           bounds_json, source_width_px, source_height_px,
                           preview_width_px, preview_height_px, source_size_bytes,
                           mime_type, created_at, updated_at
                    FROM geotiff_assets
                    WHERE asset_id = ?
                    """,
                    (asset_id,),
                ).fetchone()
        return self._row_to_asset(row) if row else None

    def save_asset(
        self,
        *,
        name: Optional[str],
        source_filename: Optional[str],
        bounds: Dict,
        source_bytes: bytes,
        preview_bytes: bytes,
        preview_meta: Dict,
        mime_type: str = "image/tiff",
        asset_id: Optional[str] = None,
    ) -> Dict:
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        asset_id = asset_id or f"geotiff-{int(time.time())}-{secrets.token_hex(4)}"
        asset_dir = self._asset_dir(asset_id)
        normalized_filename = self._normalize_name(source_filename or name)
        source_path = asset_dir / normalized_filename
        preview_path = asset_dir / "preview.png"
        bounds_json = json.dumps(bounds, separators=(",", ":"), sort_keys=True)

        source_path.write_bytes(source_bytes)
        preview_path.write_bytes(preview_bytes)

        record = {
            "asset_id": asset_id,
            "name": name or Path(normalized_filename).stem,
            "source_filename": normalized_filename,
            "source_path": str(source_path),
            "preview_path": str(preview_path),
            "bounds_json": bounds_json,
            "source_width_px": int(preview_meta["source_width_px"]),
            "source_height_px": int(preview_meta["source_height_px"]),
            "preview_width_px": int(preview_meta["preview_width_px"]),
            "preview_height_px": int(preview_meta["preview_height_px"]),
            "source_size_bytes": len(source_bytes),
            "mime_type": mime_type,
            "created_at": created_at,
            "updated_at": created_at,
        }

        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO geotiff_assets (
                        asset_id, name, source_filename, source_path, preview_path,
                        bounds_json, source_width_px, source_height_px, preview_width_px,
                        preview_height_px, source_size_bytes, mime_type, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                        name = excluded.name,
                        source_filename = excluded.source_filename,
                        source_path = excluded.source_path,
                        preview_path = excluded.preview_path,
                        bounds_json = excluded.bounds_json,
                        source_width_px = excluded.source_width_px,
                        source_height_px = excluded.source_height_px,
                        preview_width_px = excluded.preview_width_px,
                        preview_height_px = excluded.preview_height_px,
                        source_size_bytes = excluded.source_size_bytes,
                        mime_type = excluded.mime_type,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record["asset_id"],
                        record["name"],
                        record["source_filename"],
                        record["source_path"],
                        record["preview_path"],
                        record["bounds_json"],
                        record["source_width_px"],
                        record["source_height_px"],
                        record["preview_width_px"],
                        record["preview_height_px"],
                        record["source_size_bytes"],
                        record["mime_type"],
                        record["created_at"],
                        record["updated_at"],
                    ),
                )

        return self.get_asset(asset_id) or record

    def delete_asset(self, asset_id: str) -> bool:
        asset = self.get_asset(asset_id)
        if not asset:
            return False

        with self._lock:
            with self._connect() as connection:
                connection.execute("DELETE FROM geotiff_assets WHERE asset_id = ?", (asset_id,))

        asset_dir = self.asset_directory / asset_id
        if asset_dir.exists():
            shutil.rmtree(asset_dir, ignore_errors=True)
        return True
