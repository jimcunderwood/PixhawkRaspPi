"""
SQLite-backed telemetry store.

Keeps normalized telemetry samples on disk for historical analysis while
preserving the latest snapshot in memory for fast API/WebSocket access.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def _as_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class TelemetryDatabaseConfig:
    path: Path
    max_bytes: int = 64 * 1024 * 1024
    backup_count: int = 10
    vacuum_interval_seconds: int = 3600


class TelemetryDatabase:
    """SQLite persistence for telemetry snapshots."""

    def __init__(self, config: TelemetryDatabaseConfig):
        self.config = config
        self.path = Path(config.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_vacuum_at = 0.0
        self._conn = self._connect()
        self._ensure_schema()

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def record(self, snapshot: Dict) -> int:
        """Insert a telemetry snapshot into the database."""
        timestamp = _as_float(snapshot.get("timestamp")) or time.time()
        datetime_value = snapshot.get("datetime") or datetime.fromtimestamp(timestamp).isoformat()
        payload = snapshot.get("payload")
        payload_json = _json_dumps(payload or {}) if payload is not None else None
        raw_json = _json_dumps(snapshot)

        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO telemetry_samples (
                    timestamp,
                    datetime,
                    armed,
                    mode,
                    ground_speed,
                    air_speed,
                    heading,
                    is_armable,
                    system_status,
                    raw_json,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    datetime_value,
                    _as_int(snapshot.get("armed")),
                    snapshot.get("mode"),
                    _as_float(snapshot.get("ground_speed")),
                    _as_float(snapshot.get("air_speed")),
                    _as_float(snapshot.get("heading")),
                    _as_int(snapshot.get("is_armable")),
                    snapshot.get("system_status"),
                    raw_json,
                    payload_json,
                ),
            )
            sample_id = int(cursor.lastrowid)

            self._store_location(cursor, sample_id, snapshot.get("location") or {})
            self._store_attitude(cursor, sample_id, snapshot.get("attitude") or {})
            self._store_velocity(cursor, sample_id, snapshot.get("velocity") or {})
            self._store_battery(cursor, sample_id, snapshot.get("battery") or {})
            self._store_gps(cursor, sample_id, snapshot.get("gps") or {})
            self._store_rtk(cursor, sample_id, snapshot.get("rtk") or {})
            self._store_terrain(cursor, sample_id, snapshot.get("terrain") or {})
            self._store_payload(cursor, sample_id, payload or snapshot.get("payload_status") or {})

            conn.commit()
            self._maybe_rotate_locked()
            self._maybe_compact_locked()
            return sample_id

    def query(self, seconds: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        """Return telemetry snapshots in chronological order."""
        cutoff = time.time() - seconds if seconds is not None else None
        rows: List[Dict] = []

        with self._lock:
            for db_path in self._database_paths_locked():
                rows.extend(self._query_database(db_path, cutoff=cutoff, limit=limit))

        rows.sort(key=lambda item: item.get("timestamp", 0))
        if limit is not None and limit > 0:
            rows = rows[-limit:]
        return rows

    def statistics(self, seconds: int = 60) -> Dict:
        history = self.query(seconds=seconds)
        if not history:
            return {}

        stats = {
            "count": len(history),
            "duration": seconds,
            "start_time": history[0]["timestamp"],
            "end_time": history[-1]["timestamp"],
        }

        battery_levels = [
            point.get("battery", {}).get("level_percent")
            for point in history
            if point.get("battery", {}).get("level_percent") is not None
        ]
        if battery_levels:
            stats["battery"] = {
                "min": min(battery_levels),
                "max": max(battery_levels),
                "avg": sum(battery_levels) / len(battery_levels),
                "current": battery_levels[-1],
            }

        altitudes = [
            point.get("location", {}).get("altitude")
            for point in history
            if point.get("location", {}).get("altitude") is not None
        ]
        if altitudes:
            stats["altitude"] = {
                "min": min(altitudes),
                "max": max(altitudes),
                "avg": sum(altitudes) / len(altitudes),
                "current": altitudes[-1],
            }

        speeds = [point.get("ground_speed", 0) or 0 for point in history]
        if speeds:
            stats["ground_speed"] = {
                "min": min(speeds),
                "max": max(speeds),
                "avg": sum(speeds) / len(speeds),
                "current": speeds[-1],
            }

        return stats

    def clear(self):
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telemetry_attitude")
            cursor.execute("DELETE FROM telemetry_battery")
            cursor.execute("DELETE FROM telemetry_gps")
            cursor.execute("DELETE FROM telemetry_location")
            cursor.execute("DELETE FROM telemetry_payload")
            cursor.execute("DELETE FROM telemetry_rtk")
            cursor.execute("DELETE FROM telemetry_samples")
            conn.commit()
            self._maybe_compact_locked(force=True)

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
            CREATE TABLE IF NOT EXISTS telemetry_samples (
                sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                datetime TEXT NOT NULL,
                armed INTEGER,
                mode TEXT,
                ground_speed REAL,
                air_speed REAL,
                heading REAL,
                is_armable INTEGER,
                system_status TEXT,
                raw_json TEXT NOT NULL,
                payload_json TEXT
            );

            CREATE TABLE IF NOT EXISTS telemetry_location (
                sample_id INTEGER PRIMARY KEY,
                latitude REAL,
                longitude REAL,
                altitude REAL,
                FOREIGN KEY(sample_id) REFERENCES telemetry_samples(sample_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_attitude (
                sample_id INTEGER PRIMARY KEY,
                roll REAL,
                pitch REAL,
                yaw REAL,
                FOREIGN KEY(sample_id) REFERENCES telemetry_samples(sample_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_velocity (
                sample_id INTEGER PRIMARY KEY,
                north REAL,
                east REAL,
                down REAL,
                FOREIGN KEY(sample_id) REFERENCES telemetry_samples(sample_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_battery (
                sample_id INTEGER PRIMARY KEY,
                voltage REAL,
                current REAL,
                level_percent REAL,
                FOREIGN KEY(sample_id) REFERENCES telemetry_samples(sample_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_gps (
                sample_id INTEGER PRIMARY KEY,
                fix_type INTEGER,
                fix_name TEXT,
                satellite_count INTEGER,
                horizontal_accuracy REAL,
                vertical_accuracy REAL,
                FOREIGN KEY(sample_id) REFERENCES telemetry_samples(sample_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_rtk (
                sample_id INTEGER PRIMARY KEY,
                enabled_by_fix INTEGER,
                fix_type INTEGER,
                fix_name TEXT,
                is_float INTEGER,
                is_fixed INTEGER,
                FOREIGN KEY(sample_id) REFERENCES telemetry_samples(sample_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_terrain (
                sample_id INTEGER PRIMARY KEY,
                rangefinder_distance_meters REAL,
                source TEXT,
                coverage_mode TEXT,
                available INTEGER,
                FOREIGN KEY(sample_id) REFERENCES telemetry_samples(sample_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_payload (
                sample_id INTEGER PRIMARY KEY,
                payload_json TEXT,
                spray_status TEXT,
                spray_total_volume_liters REAL,
                spray_flow_rate_liters_per_minute REAL,
                camera_available INTEGER,
                camera_is_recording INTEGER,
                tank_level_percent REAL,
                pressure_psi REAL,
                FOREIGN KEY(sample_id) REFERENCES telemetry_samples(sample_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_telemetry_samples_timestamp
                ON telemetry_samples(timestamp);
            CREATE INDEX IF NOT EXISTS idx_telemetry_samples_mode
                ON telemetry_samples(mode);
            """
        )
        conn.commit()

    def _database_paths_locked(self) -> List[Path]:
        pattern = f"{self.path.name}.*"
        paths = [self.path]
        if self.path.exists():
            paths.extend(
                sorted(
                    (
                        candidate
                        for candidate in self.path.parent.glob(pattern)
                        if candidate.is_file()
                    ),
                    key=lambda candidate: candidate.stat().st_mtime,
                )
            )
        return paths

    def _query_database(self, db_path: Path, cutoff: Optional[float] = None, limit: Optional[int] = None) -> List[Dict]:
        if not db_path.exists():
            return []

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            query = [
                """
                SELECT
                    s.sample_id,
                    s.timestamp,
                    s.datetime,
                    s.armed,
                    s.mode,
                    s.ground_speed,
                    s.air_speed,
                    s.heading,
                    s.is_armable,
                    s.system_status,
                    s.raw_json,
                    s.payload_json,
                    l.latitude,
                    l.longitude,
                    l.altitude,
                    a.roll,
                    a.pitch,
                    a.yaw,
                    v.north,
                    v.east,
                    v.down,
                    b.voltage,
                    b.current,
                    b.level_percent,
                    g.fix_type,
                    g.fix_name,
                    g.satellite_count,
                    g.horizontal_accuracy,
                    g.vertical_accuracy,
                    r.enabled_by_fix,
                    r.fix_type AS rtk_fix_type,
                    r.fix_name AS rtk_fix_name,
                    r.is_float,
                    r.is_fixed,
                    t.rangefinder_distance_meters,
                    t.source AS terrain_source,
                    t.coverage_mode,
                    t.available AS terrain_available
                FROM telemetry_samples s
                LEFT JOIN telemetry_location l ON l.sample_id = s.sample_id
                LEFT JOIN telemetry_attitude a ON a.sample_id = s.sample_id
                LEFT JOIN telemetry_velocity v ON v.sample_id = s.sample_id
                LEFT JOIN telemetry_battery b ON b.sample_id = s.sample_id
                LEFT JOIN telemetry_gps g ON g.sample_id = s.sample_id
                LEFT JOIN telemetry_rtk r ON r.sample_id = s.sample_id
                LEFT JOIN telemetry_terrain t ON t.sample_id = s.sample_id
                """
            ]
            params: List[object] = []
            if cutoff is not None:
                query.append("WHERE s.timestamp >= ?")
                params.append(cutoff)
            query.append("ORDER BY s.timestamp ASC")
            cursor = conn.execute("\n".join(query), params)
            rows = [self._row_to_snapshot(row) for row in cursor.fetchall()]
            return rows
        finally:
            conn.close()

    def _row_to_snapshot(self, row: sqlite3.Row) -> Dict:
        raw = json.loads(row["raw_json"])
        if row["payload_json"]:
            raw["payload"] = json.loads(row["payload_json"])

        location = raw.setdefault("location", {})
        if row["latitude"] is not None:
            location["latitude"] = row["latitude"]
        if row["longitude"] is not None:
            location["longitude"] = row["longitude"]
        if row["altitude"] is not None:
            location["altitude"] = row["altitude"]

        attitude = raw.setdefault("attitude", {})
        if row["roll"] is not None:
            attitude["roll"] = row["roll"]
        if row["pitch"] is not None:
            attitude["pitch"] = row["pitch"]
        if row["yaw"] is not None:
            attitude["yaw"] = row["yaw"]

        velocity = raw.setdefault("velocity", {})
        if row["north"] is not None:
            velocity["north"] = row["north"]
        if row["east"] is not None:
            velocity["east"] = row["east"]
        if row["down"] is not None:
            velocity["down"] = row["down"]

        battery = raw.setdefault("battery", {})
        if row["voltage"] is not None:
            battery["voltage"] = row["voltage"]
        if row["current"] is not None:
            battery["current"] = row["current"]
        if row["level_percent"] is not None:
            battery["level_percent"] = row["level_percent"]

        gps = raw.setdefault("gps", {})
        if row["fix_type"] is not None:
            gps["fix_type"] = row["fix_type"]
        if row["fix_name"] is not None:
            gps["fix_name"] = row["fix_name"]
        if row["satellite_count"] is not None:
            gps["satellite_count"] = row["satellite_count"]
        if row["horizontal_accuracy"] is not None:
            gps["horizontal_accuracy"] = row["horizontal_accuracy"]
        if row["vertical_accuracy"] is not None:
            gps["vertical_accuracy"] = row["vertical_accuracy"]

        rtk = raw.setdefault("rtk", {})
        if row["enabled_by_fix"] is not None:
            rtk["enabled_by_fix"] = bool(row["enabled_by_fix"])
        if row["rtk_fix_type"] is not None:
            rtk["fix_type"] = row["rtk_fix_type"]
        if row["rtk_fix_name"] is not None:
            rtk["fix_name"] = row["rtk_fix_name"]
        if row["is_float"] is not None:
            rtk["is_float"] = bool(row["is_float"])
        if row["is_fixed"] is not None:
            rtk["is_fixed"] = bool(row["is_fixed"])

        terrain = raw.setdefault("terrain", {})
        if row["rangefinder_distance_meters"] is not None:
            terrain["rangefinder_distance_meters"] = row["rangefinder_distance_meters"]
        if row["terrain_source"] is not None:
            terrain["source"] = row["terrain_source"]
        if row["coverage_mode"] is not None:
            terrain["coverage_mode"] = row["coverage_mode"]
        if row["terrain_available"] is not None:
            terrain["available"] = bool(row["terrain_available"])

        raw["timestamp"] = row["timestamp"]
        raw["datetime"] = row["datetime"]
        return raw

    def _store_location(self, cursor: sqlite3.Cursor, sample_id: int, location: Dict):
        cursor.execute(
            """
            INSERT OR REPLACE INTO telemetry_location (sample_id, latitude, longitude, altitude)
            VALUES (?, ?, ?, ?)
            """,
            (
                sample_id,
                _as_float(location.get("latitude")),
                _as_float(location.get("longitude")),
                _as_float(location.get("altitude")),
            ),
        )

    def _store_attitude(self, cursor: sqlite3.Cursor, sample_id: int, attitude: Dict):
        cursor.execute(
            """
            INSERT OR REPLACE INTO telemetry_attitude (sample_id, roll, pitch, yaw)
            VALUES (?, ?, ?, ?)
            """,
            (
                sample_id,
                _as_float(attitude.get("roll")),
                _as_float(attitude.get("pitch")),
                _as_float(attitude.get("yaw")),
            ),
        )

    def _store_velocity(self, cursor: sqlite3.Cursor, sample_id: int, velocity: Dict):
        cursor.execute(
            """
            INSERT OR REPLACE INTO telemetry_velocity (sample_id, north, east, down)
            VALUES (?, ?, ?, ?)
            """,
            (
                sample_id,
                _as_float(velocity.get("north")),
                _as_float(velocity.get("east")),
                _as_float(velocity.get("down")),
            ),
        )

    def _store_battery(self, cursor: sqlite3.Cursor, sample_id: int, battery: Dict):
        cursor.execute(
            """
            INSERT OR REPLACE INTO telemetry_battery (sample_id, voltage, current, level_percent)
            VALUES (?, ?, ?, ?)
            """,
            (
                sample_id,
                _as_float(battery.get("voltage")),
                _as_float(battery.get("current")),
                _as_float(battery.get("level_percent")),
            ),
        )

    def _store_gps(self, cursor: sqlite3.Cursor, sample_id: int, gps: Dict):
        cursor.execute(
            """
            INSERT OR REPLACE INTO telemetry_gps (
                sample_id, fix_type, fix_name, satellite_count, horizontal_accuracy, vertical_accuracy
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                _as_int(gps.get("fix_type")),
                gps.get("fix_name"),
                _as_int(gps.get("satellite_count")),
                _as_float(gps.get("horizontal_accuracy")),
                _as_float(gps.get("vertical_accuracy")),
            ),
        )

    def _store_rtk(self, cursor: sqlite3.Cursor, sample_id: int, rtk: Dict):
        cursor.execute(
            """
            INSERT OR REPLACE INTO telemetry_rtk (
                sample_id, enabled_by_fix, fix_type, fix_name, is_float, is_fixed
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                1 if rtk.get("enabled_by_fix") else 0 if rtk.get("enabled_by_fix") is not None else None,
                _as_int(rtk.get("fix_type")),
                rtk.get("fix_name"),
                1 if rtk.get("is_float") else 0 if rtk.get("is_float") is not None else None,
                1 if rtk.get("is_fixed") else 0 if rtk.get("is_fixed") is not None else None,
            ),
        )

    def _store_terrain(self, cursor: sqlite3.Cursor, sample_id: int, terrain: Dict):
        cursor.execute(
            """
            INSERT OR REPLACE INTO telemetry_terrain (
                sample_id, rangefinder_distance_meters, source, coverage_mode, available
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                _as_float(terrain.get("rangefinder_distance_meters")),
                terrain.get("source"),
                terrain.get("coverage_mode"),
                1 if terrain.get("available") else 0 if terrain.get("available") is not None else None,
            ),
        )

    def _store_payload(self, cursor: sqlite3.Cursor, sample_id: int, payload: Dict):
        spray = payload.get("spray_pump") if isinstance(payload, dict) else None
        flow = payload.get("flow_sensor") if isinstance(payload, dict) else None
        camera = payload.get("camera") if isinstance(payload, dict) else None
        tank = payload.get("tank_level_sensor") if isinstance(payload, dict) else None
        pressure = payload.get("pressure_sensor") if isinstance(payload, dict) else None

        cursor.execute(
            """
            INSERT OR REPLACE INTO telemetry_payload (
                sample_id,
                payload_json,
                spray_status,
                spray_total_volume_liters,
                spray_flow_rate_liters_per_minute,
                camera_available,
                camera_is_recording,
                tank_level_percent,
                pressure_psi
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                _json_dumps(payload or {}),
                (spray or {}).get("status"),
                _as_float((flow or {}).get("total_volume_liters")),
                _as_float((flow or {}).get("flow_rate_liters_per_minute")),
                1 if (camera or {}).get("available") else 0 if camera is not None else None,
                1 if (camera or {}).get("is_recording") else 0 if camera is not None else None,
                _as_float((tank or {}).get("value")),
                _as_float((pressure or {}).get("value")),
            ),
        )

    def _maybe_rotate_locked(self):
        if not self.path.exists():
            return

        try:
            if self.path.stat().st_size < self.config.max_bytes:
                return
        except OSError:
            return

        if self._conn is not None:
            self._conn.close()
            self._conn = None

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rotated_path = self.path.with_name(f"{self.path.name}.{timestamp}")
        try:
            os.replace(self.path, rotated_path)
            logger.info("Rotated telemetry database to %s", rotated_path)
        except OSError as e:
            logger.error("Failed to rotate telemetry database %s: %s", self.path, str(e))
            self._conn = self._connect()
            self._ensure_schema()
            return

        self._prune_backups_locked()
        self._conn = self._connect()
        self._ensure_schema()

    def _prune_backups_locked(self):
        if self.config.backup_count <= 0:
            return

        archives = sorted(
            (
                candidate
                for candidate in self.path.parent.glob(f"{self.path.name}.*")
                if candidate.is_file()
            ),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        for candidate in archives[self.config.backup_count :]:
            try:
                candidate.unlink()
            except OSError as e:
                logger.warning("Failed to prune telemetry archive %s: %s", candidate, str(e))

    def _maybe_compact_locked(self, force: bool = False):
        now = time.time()
        if not force and (now - self._last_vacuum_at) < max(0, self.config.vacuum_interval_seconds):
            return

        conn = self._ensure_connection_locked()
        try:
            conn.execute("VACUUM")
            conn.commit()
            self._last_vacuum_at = now
        except sqlite3.DatabaseError as e:
            logger.debug("Telemetry database vacuum skipped: %s", str(e))
