"""SQLite-backed persistence for swarm telemetry and fusion state."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _json_dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class SwarmDatabaseConfig:
    path: Path
    max_bytes: int = 32 * 1024 * 1024
    backup_count: int = 5
    vacuum_interval_seconds: int = 3600


class SwarmDatabase:
    """Persist swarm configuration, telemetry, alerts, and fusion state."""

    def __init__(self, config: SwarmDatabaseConfig):
        self.config = config
        self.path = Path(config.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._last_vacuum_at = 0.0
        self._ensure_schema()

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def save_config(self, config: Dict) -> Dict:
        swarm_id = config["swarm_id"]
        payload = json.loads(json.dumps(config))
        with self._lock:
            conn = self._ensure_connection_locked()
            conn.execute(
                """
                INSERT INTO swarm_config (swarm_id, config_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(swarm_id) DO UPDATE SET
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (swarm_id, _json_dumps(payload), time.time()),
            )
            conn.commit()
        return payload

    def load_config(self, swarm_id: Optional[str] = None) -> Optional[Dict]:
        with self._lock:
            conn = self._ensure_connection_locked()
            if swarm_id:
                cursor = conn.execute(
                    "SELECT config_json FROM swarm_config WHERE swarm_id = ?",
                    (swarm_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT config_json FROM swarm_config ORDER BY updated_at DESC LIMIT 1"
                )
            row = cursor.fetchone()
            return json.loads(row["config_json"]) if row else None

    def save_peers(self, swarm_id: str, peers: List[Dict]) -> List[Dict]:
        normalized = [json.loads(json.dumps(peer)) for peer in peers]
        with self._lock:
            conn = self._ensure_connection_locked()
            conn.execute("DELETE FROM swarm_peers WHERE swarm_id = ?", (swarm_id,))
            for peer in normalized:
                conn.execute(
                    """
                    INSERT INTO swarm_peers (swarm_id, drone_id, peer_json, last_heartbeat_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(swarm_id, drone_id) DO UPDATE SET
                        peer_json = excluded.peer_json,
                        last_heartbeat_at = excluded.last_heartbeat_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        swarm_id,
                        peer["drone_id"],
                        _json_dumps(peer),
                        peer.get("last_heartbeat_at"),
                        time.time(),
                    ),
                )
            conn.commit()
        return normalized

    def list_peers(self, swarm_id: str) -> List[Dict]:
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.execute(
                """
                SELECT peer_json, last_heartbeat_at
                FROM swarm_peers
                WHERE swarm_id = ?
                ORDER BY drone_id ASC
                """,
                (swarm_id,),
            )
            peers = []
            for row in cursor.fetchall():
                peer = json.loads(row["peer_json"])
                peer["last_heartbeat_at"] = row["last_heartbeat_at"]
                peers.append(peer)
            return peers

    def update_peer_heartbeat(self, swarm_id: str, drone_id: str, heartbeat_at: Optional[float] = None) -> Optional[Dict]:
        heartbeat_at = heartbeat_at or time.time()
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.execute(
                """
                UPDATE swarm_peers
                SET last_heartbeat_at = ?, updated_at = ?
                WHERE swarm_id = ? AND drone_id = ?
                """,
                (heartbeat_at, time.time(), swarm_id, drone_id),
            )
            if cursor.rowcount == 0:
                return None
            conn.commit()
        return self.get_peer(swarm_id, drone_id)

    def get_peer(self, swarm_id: str, drone_id: str) -> Optional[Dict]:
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.execute(
                """
                SELECT peer_json, last_heartbeat_at
                FROM swarm_peers
                WHERE swarm_id = ? AND drone_id = ?
                """,
                (swarm_id, drone_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            peer = json.loads(row["peer_json"])
            peer["last_heartbeat_at"] = row["last_heartbeat_at"]
            return peer

    def record_telemetry(self, message: Dict) -> Dict:
        payload = json.loads(json.dumps(message))
        with self._lock:
            conn = self._ensure_connection_locked()
            conn.execute(
                """
                INSERT OR REPLACE INTO swarm_telemetry_samples (
                    sample_id,
                    swarm_id,
                    source_drone_id,
                    sequence,
                    timestamp,
                    received_at,
                    role,
                    location_json,
                    velocity_json,
                    quality_json,
                    vehicle_json,
                    link_json,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["sample_id"],
                    payload["swarm_id"],
                    payload["source_drone_id"],
                    payload["sequence"],
                    payload["timestamp"],
                    payload["received_at"],
                    payload["role"],
                    _json_dumps(payload["location"]),
                    _json_dumps(payload.get("velocity")) if payload.get("velocity") is not None else None,
                    _json_dumps(payload.get("quality")) if payload.get("quality") is not None else None,
                    _json_dumps(payload.get("vehicle")) if payload.get("vehicle") is not None else None,
                    _json_dumps(payload.get("link")) if payload.get("link") is not None else None,
                    _json_dumps(payload),
                ),
            )
            conn.commit()
            self._maybe_rotate_locked()
            self._maybe_compact_locked()
        return payload

    def list_telemetry(self, swarm_id: str, seconds: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        cutoff = time.time() - seconds if seconds is not None else None
        with self._lock:
            conn = self._ensure_connection_locked()
            query = [
                """
                SELECT raw_json
                FROM swarm_telemetry_samples
                WHERE swarm_id = ?
                """
            ]
            params: List[object] = [swarm_id]
            if cutoff is not None:
                query.append("AND timestamp >= ?")
                params.append(cutoff)
            query.append("ORDER BY timestamp ASC")
            cursor = conn.execute("\n".join(query), params)
            rows = [json.loads(row["raw_json"]) for row in cursor.fetchall()]
            if limit is not None and limit > 0:
                rows = rows[-limit:]
            return rows

    def clear_telemetry(self, swarm_id: Optional[str] = None):
        with self._lock:
            conn = self._ensure_connection_locked()
            if swarm_id is None:
                conn.execute("DELETE FROM swarm_telemetry_samples")
                conn.execute("DELETE FROM swarm_alerts")
                conn.execute("DELETE FROM swarm_fusion_state")
            else:
                conn.execute("DELETE FROM swarm_telemetry_samples WHERE swarm_id = ?", (swarm_id,))
                conn.execute("DELETE FROM swarm_alerts WHERE swarm_id = ?", (swarm_id,))
                conn.execute("DELETE FROM swarm_fusion_state WHERE swarm_id = ?", (swarm_id,))
            conn.commit()
            self._maybe_compact_locked(force=True)

    def record_fusion_state(self, state: Dict) -> Dict:
        payload = json.loads(json.dumps(state))
        with self._lock:
            conn = self._ensure_connection_locked()
            conn.execute(
                """
                INSERT INTO swarm_fusion_state (swarm_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(swarm_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (payload["swarm_id"], _json_dumps(payload), time.time()),
            )
            conn.commit()
        return payload

    def get_fusion_state(self, swarm_id: str) -> Optional[Dict]:
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.execute(
                "SELECT state_json FROM swarm_fusion_state WHERE swarm_id = ?",
                (swarm_id,),
            )
            row = cursor.fetchone()
            return json.loads(row["state_json"]) if row else None

    def record_alerts(self, swarm_id: str, sample_id: str, alerts: List[Dict]) -> List[Dict]:
        normalized = [json.loads(json.dumps(alert)) for alert in alerts]
        created_at = time.time()
        with self._lock:
            conn = self._ensure_connection_locked()
            for alert in normalized:
                conn.execute(
                    """
                    INSERT INTO swarm_alerts (
                        swarm_id,
                        sample_id,
                        drone_id_a,
                        drone_id_b,
                        horizontal_m,
                        vertical_m,
                        threshold_m,
                        severity,
                        suggested_action,
                        created_at,
                        alert_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        swarm_id,
                        sample_id,
                        alert["drone_id_a"],
                        alert["drone_id_b"],
                        alert["horizontal_m"],
                        alert["vertical_m"],
                        alert["threshold_m"],
                        alert["severity"],
                        alert.get("suggested_action"),
                        created_at,
                        _json_dumps(alert),
                    ),
                )
            conn.commit()
        return normalized

    def list_alerts(self, swarm_id: str, seconds: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        cutoff = time.time() - seconds if seconds is not None else None
        with self._lock:
            conn = self._ensure_connection_locked()
            query = [
                """
                SELECT alert_json
                FROM swarm_alerts
                WHERE swarm_id = ?
                """
            ]
            params: List[object] = [swarm_id]
            if cutoff is not None:
                query.append("AND created_at >= ?")
                params.append(cutoff)
            query.append("ORDER BY created_at DESC, alert_id DESC")
            if limit is not None and limit > 0:
                query.append("LIMIT ?")
                params.append(limit)
            cursor = conn.execute("\n".join(query), params)
            return [json.loads(row["alert_json"]) for row in cursor.fetchall()]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        return conn

    def _ensure_connection_locked(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._connect()
            self._ensure_schema()
        return self._conn

    def _ensure_schema(self):
        conn = self._conn
        if conn is None:
            return
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS swarm_config (
                swarm_id TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS swarm_peers (
                swarm_id TEXT NOT NULL,
                drone_id TEXT NOT NULL,
                peer_json TEXT NOT NULL,
                last_heartbeat_at REAL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (swarm_id, drone_id)
            );

            CREATE TABLE IF NOT EXISTS swarm_telemetry_samples (
                sample_id TEXT PRIMARY KEY,
                swarm_id TEXT NOT NULL,
                source_drone_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                received_at REAL NOT NULL,
                role TEXT NOT NULL,
                location_json TEXT NOT NULL,
                velocity_json TEXT,
                quality_json TEXT,
                vehicle_json TEXT,
                link_json TEXT,
                raw_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS swarm_fusion_state (
                swarm_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS swarm_alerts (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                swarm_id TEXT NOT NULL,
                sample_id TEXT NOT NULL,
                drone_id_a TEXT NOT NULL,
                drone_id_b TEXT NOT NULL,
                horizontal_m REAL NOT NULL,
                vertical_m REAL NOT NULL,
                threshold_m REAL NOT NULL,
                severity TEXT NOT NULL,
                suggested_action TEXT,
                created_at REAL NOT NULL,
                alert_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_swarm_telemetry_swarm_timestamp
                ON swarm_telemetry_samples(swarm_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_swarm_alerts_swarm_created
                ON swarm_alerts(swarm_id, created_at);
            """
        )
        conn.commit()

    def _database_paths_locked(self) -> List[Path]:
        pattern = f"{self.path.name}.*"
        paths = [self.path]
        if self.path.exists():
            paths.extend(
                sorted(
                    (candidate for candidate in self.path.parent.glob(pattern) if candidate.is_file()),
                    key=lambda candidate: candidate.stat().st_mtime,
                )
            )
        return paths

    def _maybe_rotate_locked(self):
        if self.path.stat().st_size < self.config.max_bytes:
            return

        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

        rotated_path = self.path.with_name(f"{self.path.name}.{int(time.time())}")
        try:
            self.path.rename(rotated_path)
            logger.info("Rotated swarm database to %s", rotated_path)
        except Exception as exc:
            logger.error("Failed to rotate swarm database %s: %s", self.path, exc)
        finally:
            self._conn = self._connect()
            self._ensure_schema()
            self._prune_archives_locked()

    def _prune_archives_locked(self):
        if self.config.backup_count <= 0:
            return

        archives = [
            path
            for path in self.path.parent.glob(f"{self.path.name}.*")
            if path.is_file()
        ]
        archives.sort(key=lambda candidate: candidate.stat().st_mtime, reverse=True)
        for candidate in archives[self.config.backup_count :]:
            try:
                candidate.unlink()
            except OSError as exc:
                logger.warning("Failed to prune swarm archive %s: %s", candidate, exc)

    def _maybe_compact_locked(self, force: bool = False):
        now = time.time()
        if not force and (now - self._last_vacuum_at) < max(0, self.config.vacuum_interval_seconds):
            return
        conn = self._ensure_connection_locked()
        conn.execute("VACUUM")
        conn.commit()
        self._last_vacuum_at = now
