"""RTK/PPK calibration workflows and post-processing."""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _json_dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _haversine_distance_m(a: Dict, b: Dict) -> float:
    radius_m = 6_371_000.0
    lat1 = math.radians(float(a["latitude"]))
    lon1 = math.radians(float(a["longitude"]))
    lat2 = math.radians(float(b["latitude"]))
    lon2 = math.radians(float(b["longitude"]))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    x = dlon * math.cos((lat1 + lat2) / 2.0)
    y = dlat
    return math.sqrt((x * radius_m) ** 2 + (y * radius_m) ** 2)


@dataclass(frozen=True)
class CalibrationWorkflowConfig:
    database_file: Path


class CalibrationWorkflowManager:
    """Persist base-station wizard inputs and PPK post-processing jobs."""

    def __init__(self, config: CalibrationWorkflowConfig, telemetry_history_getter=None):
        self.config = config
        self.telemetry_history_getter = telemetry_history_getter
        self.path = Path(config.database_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = self._connect()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _ensure_schema(self):
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS calibration_base_stations (
                station_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                altitude_m REAL,
                antenna_height_m REAL,
                correction_port TEXT,
                correction_baudrate INTEGER,
                mount_type TEXT,
                notes TEXT,
                active INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS calibration_ppk_jobs (
                job_id TEXT PRIMARY KEY,
                session TEXT,
                base_station_id TEXT,
                telemetry_window_seconds INTEGER,
                source_label TEXT,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_json TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        self._conn.commit()

    def close(self):
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def list_base_stations(self) -> List[Dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM calibration_base_stations ORDER BY active DESC, updated_at DESC"
            )
            stations = []
            for row in cursor.fetchall():
                item = dict(row)
                item["active"] = bool(item["active"])
                stations.append(item)
            return stations

    def get_base_station(self, station_id: str) -> Optional[Dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM calibration_base_stations WHERE station_id = ?",
                (station_id,),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["active"] = bool(item["active"])
            return item

    def get_active_base_station(self) -> Optional[Dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM calibration_base_stations WHERE active = 1 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return self.get_base_station(row["station_id"])

    def save_base_station(self, payload: Dict, activate: bool = False) -> Dict:
        now = time.time()
        station_id = str(payload.get("station_id") or payload.get("name") or f"base-{int(now)}")
        record = {
            "station_id": station_id,
            "name": payload.get("name") or station_id,
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "altitude_m": payload.get("altitude_m"),
            "antenna_height_m": payload.get("antenna_height_m"),
            "correction_port": payload.get("correction_port"),
            "correction_baudrate": payload.get("correction_baudrate"),
            "mount_type": payload.get("mount_type"),
            "notes": payload.get("notes"),
            "active": 1 if activate else int(bool(payload.get("active", False))),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO calibration_base_stations (
                    station_id, name, latitude, longitude, altitude_m, antenna_height_m,
                    correction_port, correction_baudrate, mount_type, notes, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(station_id) DO UPDATE SET
                    name = excluded.name,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    altitude_m = excluded.altitude_m,
                    antenna_height_m = excluded.antenna_height_m,
                    correction_port = excluded.correction_port,
                    correction_baudrate = excluded.correction_baudrate,
                    mount_type = excluded.mount_type,
                    notes = excluded.notes,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    record["station_id"],
                    record["name"],
                    record["latitude"],
                    record["longitude"],
                    record["altitude_m"],
                    record["antenna_height_m"],
                    record["correction_port"],
                    record["correction_baudrate"],
                    record["mount_type"],
                    record["notes"],
                    record["active"],
                    record["created_at"],
                    record["updated_at"],
                ),
            )
            if activate:
                self._conn.execute("UPDATE calibration_base_stations SET active = 0")
                self._conn.execute(
                    "UPDATE calibration_base_stations SET active = 1, updated_at = ? WHERE station_id = ?",
                    (now, record["station_id"]),
                )
            self._conn.commit()
        return self.get_base_station(record["station_id"]) or record

    def activate_base_station(self, station_id: str) -> Optional[Dict]:
        with self._lock:
            station = self.get_base_station(station_id)
            if not station:
                return None
            self._conn.execute("UPDATE calibration_base_stations SET active = 0")
            self._conn.execute(
                "UPDATE calibration_base_stations SET active = 1, updated_at = ? WHERE station_id = ?",
                (time.time(), station_id),
            )
            self._conn.commit()
        return self.get_base_station(station_id)

    def _summarize_history(self, telemetry_history: List[Dict]) -> Dict:
        points = [sample for sample in telemetry_history if (sample.get("location") or {}).get("latitude") is not None]
        if not points:
            return {
                "sample_count": 0,
                "path_length_m": 0.0,
                "duration_s": 0.0,
                "average_ground_speed_mps": 0.0,
                "estimated_horizontal_accuracy_m": None,
            }

        ordered = sorted(points, key=lambda sample: float(sample.get("timestamp") or 0.0))
        path_length_m = 0.0
        for index in range(1, len(ordered)):
            previous = ordered[index - 1]["location"]
            current = ordered[index]["location"]
            path_length_m += _haversine_distance_m(previous, current)

        start_ts = float(ordered[0].get("timestamp") or 0.0)
        end_ts = float(ordered[-1].get("timestamp") or start_ts)
        duration_s = max(0.0, end_ts - start_ts)
        ground_speeds = [float(sample.get("ground_speed") or 0.0) for sample in ordered if sample.get("ground_speed") is not None]
        average_ground_speed = sum(ground_speeds) / len(ground_speeds) if ground_speeds else (path_length_m / duration_s if duration_s else 0.0)
        estimated_accuracy = max(0.05, 1.8 / math.sqrt(max(len(ordered), 1)))
        return {
            "sample_count": len(ordered),
            "path_length_m": path_length_m,
            "duration_s": duration_s,
            "average_ground_speed_mps": average_ground_speed,
            "estimated_horizontal_accuracy_m": estimated_accuracy,
            "start_at": start_ts,
            "end_at": end_ts,
        }

    def process_ppk_job(self, request: Dict) -> Dict:
        telemetry_history = request.get("telemetry_history")
        if telemetry_history is None and self.telemetry_history_getter:
            seconds = int(request.get("telemetry_window_seconds") or 600)
            telemetry_history = self.telemetry_history_getter(seconds)
        telemetry_history = list(telemetry_history or [])
        base_station = None
        if request.get("base_station_id"):
            base_station = self.get_base_station(request["base_station_id"])
        if base_station is None:
            base_station = self.get_active_base_station()

        summary = self._summarize_history(telemetry_history)
        job_id = request.get("job_id") or f"ppk-{int(time.time() * 1000)}"
        result = {
            "job_id": job_id,
            "session": request.get("session"),
            "base_station": base_station,
            "status": "complete" if summary["sample_count"] else "needs_data",
            "source_label": request.get("source_label") or "telemetry_history",
            "telemetry_window_seconds": request.get("telemetry_window_seconds"),
            "summary": summary,
            "quality": {
                "post_processed_at": time.time(),
                "estimated_position_error_m": summary["estimated_horizontal_accuracy_m"],
                "correction_applied": bool(base_station),
            },
            "notes": request.get("notes"),
        }
        with self._lock:
            now = time.time()
            self._conn.execute(
                """
                INSERT INTO calibration_ppk_jobs (
                    job_id, session, base_station_id, telemetry_window_seconds, source_label,
                    status, request_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    session = excluded.session,
                    base_station_id = excluded.base_station_id,
                    telemetry_window_seconds = excluded.telemetry_window_seconds,
                    source_label = excluded.source_label,
                    status = excluded.status,
                    request_json = excluded.request_json,
                    result_json = excluded.result_json,
                    updated_at = excluded.updated_at
                """,
                (
                    job_id,
                    request.get("session"),
                    (base_station or {}).get("station_id"),
                    request.get("telemetry_window_seconds"),
                    request.get("source_label") or "telemetry_history",
                    result["status"],
                    _json_dumps(request),
                    _json_dumps(result),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return result

    def list_ppk_jobs(self) -> List[Dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT job_id, request_json, result_json, status, updated_at FROM calibration_ppk_jobs ORDER BY updated_at DESC"
            )
            jobs = []
            for row in cursor.fetchall():
                payload = json.loads(row["result_json"]) if row["result_json"] else {"job_id": row["job_id"], "status": row["status"]}
                request_payload = json.loads(row["request_json"]) if row["request_json"] else {}
                if request_payload:
                    payload["request"] = request_payload
                payload["status"] = row["status"]
                payload["updated_at"] = row["updated_at"]
                payload["base_station_id"] = payload.get("base_station_id") or request_payload.get("base_station_id")
                jobs.append(payload)
            return jobs

    def get_status(self) -> Dict:
        base_stations = self.list_base_stations()
        jobs = self.list_ppk_jobs()
        return {
            "enabled": True,
            "rtk_enabled": bool(base_stations),
            "ppk_enabled": True,
            "base_station_count": len(base_stations),
            "active_base_station": self.get_active_base_station(),
            "base_stations": base_stations,
            "recent_jobs": jobs[:10],
            "last_job": jobs[0] if jobs else None,
            "updated_at": time.time(),
        }
