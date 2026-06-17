"""
SQLite-backed runtime configuration profiles.
"""

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


PROFILE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


class ConfigProfileStore:
    """Persist named configuration snapshots in SQLite."""

    def __init__(self, database_file: str):
        self.database_file = Path(database_file)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
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
                    CREATE TABLE IF NOT EXISTS config_profiles (
                        name TEXT PRIMARY KEY,
                        description TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        configuration_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_config_profiles_updated_at
                    ON config_profiles(updated_at)
                    """
                )

    def _safe_name(self, name: str) -> str:
        safe_name = PROFILE_NAME_PATTERN.sub("_", name.strip())
        safe_name = safe_name.strip("._-")
        if not safe_name:
            raise ValueError("Configuration profile name is required.")
        return safe_name[:120]

    def _row_to_profile(self, row: sqlite3.Row) -> Dict:
        return {
            "version": row["version"],
            "name": row["name"],
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "configuration": json.loads(row["configuration_json"]),
        }

    def list_profiles(self) -> List[Dict]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT name, description, created_at, updated_at, version, configuration_json
                    FROM config_profiles
                    ORDER BY updated_at DESC
                    """
                ).fetchall()

        profiles = []
        for row in rows:
            configuration = json.loads(row["configuration_json"])
            profiles.append(
                {
                    "name": row["name"],
                    "description": row["description"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "version": row["version"],
                    "groups": sorted(configuration.keys()),
                }
            )
        return profiles

    def get_profile(self, name: str) -> Optional[Dict]:
        safe_name = self._safe_name(name)
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT name, description, created_at, updated_at, version, configuration_json
                    FROM config_profiles
                    WHERE name = ?
                    """,
                    (safe_name,),
                ).fetchone()
        return self._row_to_profile(row) if row else None

    def save_profile(
        self,
        name: str,
        configuration: Dict,
        description: Optional[str] = None,
        overwrite: bool = True,
    ) -> Dict:
        safe_name = self._safe_name(name)
        now = datetime.now(timezone.utc).isoformat()
        configuration_json = json.dumps(configuration, separators=(",", ":"), sort_keys=True)

        with self._lock:
            with self._connect() as connection:
                existing = connection.execute(
                    "SELECT created_at FROM config_profiles WHERE name = ?",
                    (safe_name,),
                ).fetchone()
                if existing and not overwrite:
                    raise FileExistsError(f"Configuration profile already exists: {safe_name}")

                created_at = existing["created_at"] if existing else now
                connection.execute(
                    """
                    INSERT INTO config_profiles (
                        name,
                        description,
                        created_at,
                        updated_at,
                        version,
                        configuration_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        description = excluded.description,
                        updated_at = excluded.updated_at,
                        version = excluded.version,
                        configuration_json = excluded.configuration_json
                    """,
                    (safe_name, description, created_at, now, 1, configuration_json),
                )

        return self.get_profile(safe_name)
