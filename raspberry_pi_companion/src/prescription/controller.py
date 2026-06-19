"""Prescription map parsing and GPS-synchronized rate control."""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


def _json_dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _point_in_polygon(latitude: float, longitude: float, polygon: Sequence[Sequence[float]]) -> bool:
    inside = False
    if len(polygon) < 3:
        return False

    x = longitude
    y = latitude
    points = list(polygon)
    if points[0] != points[-1]:
        points.append(points[0])

    for index in range(len(points) - 1):
        lat1, lon1 = points[index][1], points[index][0]
        lat2, lon2 = points[index + 1][1], points[index + 1][0]
        intersects = ((lat1 > y) != (lat2 > y)) and (
            x < (lon2 - lon1) * (y - lat1) / ((lat2 - lat1) or 1e-9) + lon1
        )
        if intersects:
            inside = not inside
    return inside


def _distance_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    from math import cos, radians, sqrt

    earth_radius_m = 6_371_000.0
    dlat = radians(b_lat - a_lat)
    dlon = radians(b_lon - a_lon)
    mean_lat = radians((a_lat + b_lat) / 2.0)
    x = dlon * cos(mean_lat)
    y = dlat
    return sqrt((x * earth_radius_m) ** 2 + (y * earth_radius_m) ** 2)


@dataclass(frozen=True)
class PrescriptionMapConfig:
    path: Path
    max_bytes: int = 8 * 1024 * 1024
    backup_count: int = 3
    vacuum_interval_seconds: int = 3600


class PrescriptionMapStore:
    """SQLite-backed storage for prescription maps and zones."""

    def __init__(self, config: PrescriptionMapConfig):
        self.config = config
        self.path = Path(config.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = self._connect()
        self._last_vacuum_at = 0.0
        self._ensure_schema()

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA synchronous = NORMAL")
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
            CREATE TABLE IF NOT EXISTS prescription_maps (
                map_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                source_format TEXT NOT NULL,
                default_rate_lpha REAL NOT NULL,
                swath_width_m REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 0,
                raw_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prescription_zones (
                zone_id INTEGER PRIMARY KEY AUTOINCREMENT,
                map_id TEXT NOT NULL,
                label TEXT,
                target_rate_lpha REAL NOT NULL,
                geometry_type TEXT NOT NULL,
                geometry_json TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (map_id) REFERENCES prescription_maps(map_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_prescription_zones_map_priority
                ON prescription_zones(map_id, priority DESC, zone_id ASC);
            """
        )
        conn.commit()

    def save_map(self, map_payload: Dict, active: bool = False) -> Dict:
        payload = json.loads(json.dumps(map_payload))
        map_id = str(payload["map_id"])
        now = time.time()
        with self._lock:
            conn = self._ensure_connection_locked()
            conn.execute(
                """
                INSERT INTO prescription_maps (
                    map_id,
                    name,
                    description,
                    source_format,
                    default_rate_lpha,
                    swath_width_m,
                    active,
                    raw_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(map_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    source_format = excluded.source_format,
                    default_rate_lpha = excluded.default_rate_lpha,
                    swath_width_m = excluded.swath_width_m,
                    active = excluded.active,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    map_id,
                    payload.get("name") or map_id,
                    payload.get("description"),
                    payload.get("source_format", "geojson"),
                    float(payload.get("default_rate_lpha", 0.0)),
                    float(payload.get("swath_width_m", 0.0)),
                    1 if active else int(bool(payload.get("active", False))),
                    _json_dumps(payload),
                    now,
                    now,
                ),
            )
            conn.execute("DELETE FROM prescription_zones WHERE map_id = ?", (map_id,))
            for zone in payload.get("zones", []):
                conn.execute(
                    """
                    INSERT INTO prescription_zones (
                        map_id,
                        label,
                        target_rate_lpha,
                        geometry_type,
                        geometry_json,
                        priority,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        map_id,
                        zone.get("label"),
                        float(zone.get("target_rate_lpha", payload.get("default_rate_lpha", 0.0))),
                        zone.get("geometry_type", "point"),
                        _json_dumps(zone.get("geometry") or {}),
                        int(zone.get("priority", 0)),
                        now,
                        now,
                    ),
                )
            if active:
                conn.execute("UPDATE prescription_maps SET active = 0")
                conn.execute("UPDATE prescription_maps SET active = 1 WHERE map_id = ?", (map_id,))
            conn.commit()
        return self.get_map(map_id) or payload

    def list_maps(self) -> List[Dict]:
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.execute(
                "SELECT map_id, raw_json, active, updated_at FROM prescription_maps ORDER BY active DESC, updated_at DESC"
            )
            maps = []
            for row in cursor.fetchall():
                payload = json.loads(row["raw_json"])
                payload["active"] = bool(row["active"])
                payload["updated_at"] = row["updated_at"]
                maps.append(payload)
            return maps

    def get_map(self, map_id: str) -> Optional[Dict]:
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.execute(
                "SELECT raw_json, active, created_at, updated_at FROM prescription_maps WHERE map_id = ?",
                (map_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            payload = json.loads(row["raw_json"])
            payload["active"] = bool(row["active"])
            payload["created_at"] = row["created_at"]
            payload["updated_at"] = row["updated_at"]
            payload["zones"] = self.list_zones(map_id)
            return payload

    def list_zones(self, map_id: str) -> List[Dict]:
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.execute(
                """
                SELECT zone_id, label, target_rate_lpha, geometry_type, geometry_json, priority, created_at, updated_at
                FROM prescription_zones
                WHERE map_id = ?
                ORDER BY priority DESC, zone_id ASC
                """,
                (map_id,),
            )
            zones = []
            for row in cursor.fetchall():
                zones.append(
                    {
                        "zone_id": row["zone_id"],
                        "label": row["label"],
                        "target_rate_lpha": row["target_rate_lpha"],
                        "geometry_type": row["geometry_type"],
                        "geometry": json.loads(row["geometry_json"]),
                        "priority": row["priority"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
                )
            return zones

    def activate_map(self, map_id: str) -> Optional[Dict]:
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.execute("SELECT map_id FROM prescription_maps WHERE map_id = ?", (map_id,))
            if cursor.fetchone() is None:
                return None
            conn.execute("UPDATE prescription_maps SET active = 0")
            conn.execute("UPDATE prescription_maps SET active = 1, updated_at = ? WHERE map_id = ?", (time.time(), map_id))
            conn.commit()
        return self.get_map(map_id)

    def get_active_map(self) -> Optional[Dict]:
        with self._lock:
            conn = self._ensure_connection_locked()
            cursor = conn.execute(
                "SELECT map_id FROM prescription_maps WHERE active = 1 ORDER BY updated_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self.get_map(row["map_id"])


def _extract_rate(payload: Dict, default_rate: float) -> float:
    for key in (
        "target_rate_lpha",
        "target_rate",
        "rate_lpha",
        "application_rate_liters_per_hectare",
    ):
        value = payload.get(key)
        if value is not None:
            return float(value)
    return default_rate


def _normalize_polygon(geometry: Dict) -> List[List[float]]:
    coords = geometry.get("coordinates") or []
    if not coords:
        return []
    ring = coords[0] if geometry.get("type") == "Polygon" else coords[0][0]
    return [[float(lon), float(lat)] for lon, lat in ring]


class PrescriptionRateController:
    """Evaluates prescription maps against live GPS telemetry."""

    def __init__(self, config, store: PrescriptionMapStore):
        self.config = config
        self.store = store
        self._lock = threading.Lock()
        self._latest_snapshot: Dict = {}
        self._last_evaluation: Optional[Dict] = None

    def import_payload(
        self,
        payload_text: str,
        name: str,
        source_format: Optional[str] = None,
        activate: bool = True,
    ) -> Dict:
        payload_text = (payload_text or "").strip()
        if not payload_text:
            raise ValueError("Prescription map payload is empty.")

        guessed_format = (source_format or "").strip().lower()
        if not guessed_format:
            if payload_text.lstrip().startswith("{") or payload_text.lstrip().startswith("["):
                guessed_format = "geojson"
            else:
                guessed_format = "csv"

        if guessed_format == "csv":
            map_payload = self._parse_csv(payload_text, name)
        else:
            map_payload = self._parse_geojson(payload_text, name)

        saved = self.store.save_map(map_payload, active=activate)
        if activate:
            self.store.activate_map(saved["map_id"])
        return self.evaluate(self._latest_snapshot)

    def _parse_csv(self, payload_text: str, name: str) -> Dict:
        reader = csv.DictReader(payload_text.splitlines())
        rows = list(reader)
        zones = []
        default_rate = self.config.default_rate_liters_per_hectare
        swath_width = self.config.swath_width_meters
        for index, row in enumerate(rows):
            latitude = row.get("latitude") or row.get("lat")
            longitude = row.get("longitude") or row.get("lon") or row.get("lng")
            if latitude is None or longitude is None:
                continue
            target_rate = _extract_rate(row, default_rate)
            zones.append(
                {
                    "label": row.get("label") or f"cell-{index + 1}",
                    "target_rate_lpha": target_rate,
                    "priority": int(row.get("priority", index)),
                    "geometry_type": "point",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(longitude), float(latitude)],
                    },
                }
            )

        return {
            "map_id": name,
            "name": name,
            "description": f"CSV prescription map with {len(zones)} cells",
            "source_format": "csv",
            "default_rate_lpha": default_rate,
            "swath_width_m": float(swath_width),
            "zones": zones,
        }

    def _parse_geojson(self, payload_text: str, name: str) -> Dict:
        data = json.loads(payload_text)
        default_rate = float(data.get("properties", {}).get("default_rate_lpha", self.config.default_rate_liters_per_hectare))
        swath_width = float(data.get("properties", {}).get("swath_width_m", self.config.swath_width_meters))
        zones = []
        features = data.get("features", []) if isinstance(data, dict) else []
        for index, feature in enumerate(features):
            geometry = feature.get("geometry") or {}
            properties = feature.get("properties") or {}
            geometry_type = geometry.get("type")
            if geometry_type not in {"Point", "Polygon", "MultiPolygon"}:
                continue
            zone = {
                "label": properties.get("label") or properties.get("name") or f"zone-{index + 1}",
                "target_rate_lpha": _extract_rate(properties, default_rate),
                "priority": int(properties.get("priority", index)),
                "geometry_type": geometry_type.lower(),
                "geometry": geometry,
            }
            zones.append(zone)

        return {
            "map_id": str(data.get("id") or name),
            "name": data.get("name") or name,
            "description": data.get("description") or f"GeoJSON prescription map with {len(zones)} zones",
            "source_format": "geojson",
            "default_rate_lpha": default_rate,
            "swath_width_m": swath_width,
            "zones": zones,
        }

    def update_telemetry(self, snapshot: Optional[Dict]):
        with self._lock:
            self._latest_snapshot = dict(snapshot or {})

    def evaluate(self, snapshot: Optional[Dict] = None) -> Dict:
        snapshot = snapshot or self._latest_snapshot or {}
        location = snapshot.get("location") or {}
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if latitude is None or longitude is None:
            result = {
                "enabled": bool(self.config.enabled),
                "configured": False,
                "active_map": self.store.get_active_map(),
                "current_zone": None,
                "target_rate_liters_per_hectare": None,
                "current_flow_rate_liters_per_minute": None,
                "recommended_duty_cycle": None,
                "speed_sync_enabled": bool(self.config.synchronize_to_ground_speed),
                "ground_speed_mps": (snapshot.get("ground_speed") or snapshot.get("velocity", {}).get("ground_speed_mps")),
                "effective_ground_speed_mps": None,
                "swath_width_m": self.config.swath_width_meters,
                "updated_at": time.time(),
            }
            self._last_evaluation = result
            return result

        active_map = self.store.get_active_map()
        raw_ground_speed_mps = float(
            snapshot.get("ground_speed") or (snapshot.get("velocity") or {}).get("ground_speed_mps") or 0.0
        )
        ground_speed_mps = raw_ground_speed_mps
        if self.config.synchronize_to_ground_speed:
            if raw_ground_speed_mps < self.config.minimum_speed_mps:
                ground_speed_mps = 0.0
            else:
                ground_speed_mps = min(raw_ground_speed_mps, self.config.maximum_speed_mps)
        target_rate = self.config.default_rate_liters_per_hectare
        matched_zone = None

        if active_map:
            zones = active_map.get("zones") or []
            for zone in sorted(zones, key=lambda item: item.get("priority", 0), reverse=True):
                geometry = zone.get("geometry") or {}
                geometry_type = (zone.get("geometry_type") or geometry.get("type") or "").lower()
                if geometry_type == "point":
                    coords = geometry.get("coordinates") or []
                    if len(coords) >= 2 and _distance_m(latitude, longitude, float(coords[1]), float(coords[0])) <= 25.0:
                        matched_zone = zone
                        break
                else:
                    if geometry_type == "polygon":
                        polygon = _normalize_polygon(geometry)
                        if _point_in_polygon(latitude, longitude, polygon):
                            matched_zone = zone
                            break
                    elif geometry_type == "multipolygon":
                        for polygon_coords in geometry.get("coordinates") or []:
                            polygon = [[float(lon), float(lat)] for lon, lat in polygon_coords[0]]
                            if _point_in_polygon(latitude, longitude, polygon):
                                matched_zone = zone
                                break
                        if matched_zone:
                            break

            if matched_zone:
                target_rate = float(matched_zone.get("target_rate_lpha", target_rate))
            else:
                target_rate = float(active_map.get("default_rate_lpha", target_rate))

        swath_width = float(active_map.get("swath_width_m") if active_map else self.config.swath_width_meters)
        target_flow_lpm = (target_rate * max(0.0, ground_speed_mps) * swath_width / 10000.0) * 60.0
        recommended_duty_cycle = None
        if self.config.maximum_rate_liters_per_hectare > self.config.minimum_rate_liters_per_hectare:
            recommended_duty_cycle = max(
                0.0,
                min(
                    1.0,
                    (target_rate - self.config.minimum_rate_liters_per_hectare)
                    / (
                        self.config.maximum_rate_liters_per_hectare
                        - self.config.minimum_rate_liters_per_hectare
                    ),
                ),
            )

        result = {
            "enabled": bool(self.config.enabled),
            "configured": bool(active_map),
            "active_map": active_map,
            "current_zone": matched_zone,
            "target_rate_liters_per_hectare": target_rate,
            "current_flow_rate_liters_per_minute": target_flow_lpm,
            "recommended_duty_cycle": recommended_duty_cycle,
            "speed_sync_enabled": bool(self.config.synchronize_to_ground_speed),
            "ground_speed_mps": raw_ground_speed_mps,
            "effective_ground_speed_mps": ground_speed_mps,
            "swath_width_m": swath_width,
            "location": {"latitude": float(latitude), "longitude": float(longitude)},
            "updated_at": time.time(),
        }
        self._last_evaluation = result
        return result

    def get_status(self) -> Dict:
        return self._last_evaluation or self.evaluate(self._latest_snapshot)
