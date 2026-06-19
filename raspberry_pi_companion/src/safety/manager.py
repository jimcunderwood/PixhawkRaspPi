"""
Companion-side geofence, failsafe, and compliance manager.

This module keeps the companion in charge of altitude limits, no-fly zones,
progressive emergency responses, and checklist/compliance state that can be
surfaced through the API.
"""

from __future__ import annotations

import json
import logging
import math
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config.settings import SafetyConfig

logger = logging.getLogger(__name__)


@dataclass
class GeofenceZone:
    name: str
    zone_type: str = "no_fly"
    polygon: List[Dict[str, float]] = field(default_factory=list)
    min_altitude_m: Optional[float] = None
    max_altitude_m: Optional[float] = None
    active: bool = True
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "zone_type": self.zone_type,
            "polygon": self.polygon,
            "min_altitude_m": self.min_altitude_m,
            "max_altitude_m": self.max_altitude_m,
            "active": self.active,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "GeofenceZone":
        return cls(
            name=str(data.get("name", "")).strip(),
            zone_type=str(data.get("zone_type", "no_fly")).strip().lower(),
            polygon=list(data.get("polygon") or []),
            min_altitude_m=data.get("min_altitude_m"),
            max_altitude_m=data.get("max_altitude_m"),
            active=bool(data.get("active", True)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class RemoteIDState:
    enabled: bool = False
    broadcast_method: str = "mavlink"
    operator_id: str = ""
    serial_number: str = ""
    description: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    last_updated_at: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "broadcast_method": self.broadcast_method,
            "operator_id": self.operator_id,
            "serial_number": self.serial_number,
            "description": self.description,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude_m": self.altitude_m,
            "last_updated_at": self.last_updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "RemoteIDState":
        return cls(
            enabled=bool(data.get("enabled", False)),
            broadcast_method=str(data.get("broadcast_method", "mavlink")),
            operator_id=str(data.get("operator_id", "")),
            serial_number=str(data.get("serial_number", "")),
            description=str(data.get("description", "")),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            altitude_m=data.get("altitude_m"),
            last_updated_at=data.get("last_updated_at"),
        )


@dataclass
class WaiverState:
    night_flight_authorized: bool = False
    bvlos_authorized: bool = False
    notes: str = ""
    last_updated_at: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "night_flight_authorized": self.night_flight_authorized,
            "bvlos_authorized": self.bvlos_authorized,
            "notes": self.notes,
            "last_updated_at": self.last_updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "WaiverState":
        return cls(
            night_flight_authorized=bool(data.get("night_flight_authorized", False)),
            bvlos_authorized=bool(data.get("bvlos_authorized", False)),
            notes=str(data.get("notes", "")),
            last_updated_at=data.get("last_updated_at"),
        )


class SafetyManager:
    """Evaluate companion-side safety and compliance state."""

    def __init__(self, config: SafetyConfig, connection_manager=None, telemetry_manager=None):
        self.config = config
        self.connection_manager = connection_manager
        self.telemetry_manager = telemetry_manager
        self.state_file = self._resolve_state_file(Path(config.safety_state_file))
        self._lock = threading.RLock()
        self._zones: List[GeofenceZone] = []
        self._remote_id = RemoteIDState(
            enabled=config.remote_id_enabled,
            broadcast_method=config.remote_id_broadcast_method,
            operator_id=config.remote_id_operator_id,
            serial_number=config.remote_id_serial_number,
            description=config.remote_id_description,
        )
        self._waivers = WaiverState(
            night_flight_authorized=config.part107_night_authorized,
            bvlos_authorized=config.part107_bvlos_authorized,
            notes=config.part107_waiver_notes,
        )
        self._last_evaluation: Dict = {}
        self._last_action: Optional[str] = None
        self._last_snapshot: Optional[Dict] = None
        self._last_action_at: Optional[float] = None
        self._load_state()

    def _resolve_state_file(self, preferred: Path) -> Path:
        try:
            preferred.parent.mkdir(parents=True, exist_ok=True)
            return preferred
        except OSError:
            fallback = Path(tempfile.gettempdir()) / "drone-companion" / "safety" / preferred.name
            fallback.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Falling back to writable safety state file %s", fallback)
            return fallback

    def _load_state(self):
        if not self.state_file.is_file():
            return

        try:
            with self.state_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Unable to load safety state file %s: %s", self.state_file, str(e))
            return

        self._zones = [GeofenceZone.from_dict(item) for item in data.get("zones", [])]
        self._remote_id = RemoteIDState.from_dict(data.get("remote_id", {}))
        self._waivers = WaiverState.from_dict(data.get("waivers", {}))

    def _save_state(self):
        payload = {
            "zones": [zone.to_dict() for zone in self._zones],
            "remote_id": self._remote_id.to_dict(),
            "waivers": self._waivers.to_dict(),
            "updated_at": time.time(),
            "updated_at_iso": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        tmp_path = self.state_file.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            tmp_path.replace(self.state_file)
        except OSError as e:
            logger.error("Failed to persist safety state: %s", str(e))

    def register_telemetry_point(self, point):
        snapshot = point.to_dict() if hasattr(point, "to_dict") else dict(point)
        with self._lock:
            self._last_snapshot = snapshot
            self._last_evaluation = self.evaluate_snapshot(snapshot)
            action = self._last_evaluation.get("recommended_action")
        if action and self.config.autonomous_failsafe_enabled:
            self._maybe_apply_action(action)

    def _maybe_apply_action(self, action: str):
        if not self.connection_manager:
            return
        if action == self._last_action and self._last_action_at and (time.time() - self._last_action_at) < 3:
            return

        try:
            if action == "rtl":
                self.connection_manager.set_mode("RTL")
            elif action == "land":
                self.connection_manager.land()
            elif action == "loiter":
                self.connection_manager.set_mode("LOITER")
            elif action == "hold":
                self.connection_manager.set_mode("LOITER")
            self._last_action = action
            self._last_action_at = time.time()
        except Exception as e:
            logger.warning("Safety action %s failed: %s", action, str(e))

    def list_zones(self) -> List[Dict]:
        with self._lock:
            return [zone.to_dict() for zone in self._zones]

    def upsert_zone(self, zone: GeofenceZone) -> Dict:
        with self._lock:
            self._zones = [existing for existing in self._zones if existing.name != zone.name]
            self._zones.append(zone)
            self._save_state()
            return zone.to_dict()

    def delete_zone(self, name: str) -> bool:
        with self._lock:
            before = len(self._zones)
            self._zones = [zone for zone in self._zones if zone.name != name]
            removed = len(self._zones) != before
            if removed:
                self._save_state()
            return removed

    def get_remote_id(self) -> Dict:
        with self._lock:
            return self._remote_id.to_dict()

    def update_remote_id(self, data: Dict) -> Dict:
        with self._lock:
            merged = self._remote_id.to_dict()
            merged.update({key: value for key, value in data.items() if value is not None})
            merged["last_updated_at"] = time.time()
            self._remote_id = RemoteIDState.from_dict(merged)
            self._save_state()
            return self._remote_id.to_dict()

    def get_waivers(self) -> Dict:
        with self._lock:
            return self._waivers.to_dict()

    def update_waivers(self, data: Dict) -> Dict:
        with self._lock:
            merged = self._waivers.to_dict()
            merged.update({key: value for key, value in data.items() if value is not None})
            merged["last_updated_at"] = time.time()
            self._waivers = WaiverState.from_dict(merged)
            self._save_state()
            return self._waivers.to_dict()

    def get_status(self) -> Dict:
        with self._lock:
            snapshot = dict(self._last_snapshot or {})
            evaluation = dict(self._last_evaluation or {})

        return {
            "active_zones": len(self._zones),
            "zones": [zone.to_dict() for zone in self._zones],
            "remote_id": self.get_remote_id(),
            "waivers": self.get_waivers(),
            "last_action": self._last_action,
            "last_action_at": self._last_action_at,
            "last_evaluation": evaluation,
            "last_snapshot": snapshot,
        }

    def evaluate_snapshot(self, snapshot: Dict) -> Dict:
        location = snapshot.get("location") or {}
        battery = snapshot.get("battery") or {}
        gps = snapshot.get("gps") or {}
        groundspeed = self._numeric(snapshot.get("ground_speed"))
        airspeed = self._numeric(snapshot.get("air_speed"))
        altitude = self._numeric(location.get("altitude"))
        latitude = self._numeric(location.get("latitude"))
        longitude = self._numeric(location.get("longitude"))
        battery_level = self._numeric(battery.get("level_percent"))
        telemetry_age = self._telemetry_age_seconds(snapshot)

        soft_min = self.config.altitude_soft_min_m
        soft_max = self.config.altitude_soft_max_m
        if groundspeed is not None and groundspeed > self.config.dynamic_geofence_speed_threshold_mps:
            soft_max = max(
                self.config.altitude_soft_min_m,
                soft_max - ((groundspeed - self.config.dynamic_geofence_speed_threshold_mps) * self.config.dynamic_geofence_soft_ceiling_reduction_m_per_mps),
            )

        blockers: List[str] = []
        warnings: List[str] = []
        recommended_action = "none"

        if altitude is not None:
            if altitude < self.config.altitude_hard_min_m or altitude > self.config.altitude_hard_max_m:
                blockers.append("Altitude is outside hard geofence limits.")
                recommended_action = "land" if altitude < self.config.altitude_hard_min_m else "rtl"
            elif altitude < soft_min or altitude > soft_max:
                warnings.append("Altitude is outside soft geofence limits.")
                if recommended_action == "none":
                    recommended_action = "hold"

        zone_hit = self._find_zone_hit(latitude, longitude)
        if zone_hit:
            if zone_hit.zone_type == "no_fly":
                blockers.append(f"Current position is inside no-fly zone: {zone_hit.name}.")
                recommended_action = "land"
            elif zone_hit.zone_type in {"landing_zone", "emergency_landing"}:
                warnings.append(f"Current position is inside landing zone: {zone_hit.name}.")

        if battery_level is not None:
            if battery_level <= self.config.low_battery_land_percent:
                blockers.append("Battery is critically low.")
                recommended_action = "land"
            elif battery_level <= self.config.low_battery_rtl_percent:
                warnings.append("Battery is low enough to trigger RTL.")
                recommended_action = "rtl" if recommended_action == "none" else recommended_action
            elif battery_level <= self.config.low_battery_warn_percent:
                warnings.append("Battery is below warning threshold.")

        if gps.get("fix_type", 0) < 3:
            warnings.append("GPS fix is degraded.")
            if telemetry_age is not None and telemetry_age > self.config.gps_loss_land_seconds:
                blockers.append("GPS loss timeout reached.")
                recommended_action = "land"
            elif telemetry_age is not None and telemetry_age > self.config.gps_loss_rtl_seconds:
                recommended_action = "rtl"
            elif telemetry_age is not None and telemetry_age > self.config.gps_loss_warn_seconds:
                recommended_action = "hold" if recommended_action == "none" else recommended_action

        if telemetry_age is not None and telemetry_age > self.config.lost_link_land_seconds:
            blockers.append("Lost-link timeout reached.")
            recommended_action = "land"
        elif telemetry_age is not None and telemetry_age > self.config.lost_link_rtl_seconds:
            warnings.append("Lost-link timeout approaching RTL threshold.")
            if recommended_action == "none":
                recommended_action = "rtl"
        elif telemetry_age is not None and telemetry_age > self.config.lost_link_warn_seconds:
            warnings.append("Telemetry age indicates degraded link health.")

        landing_zone = self.identify_emergency_landing_zone(latitude, longitude)

        evaluation = {
            "blockers": blockers,
            "warnings": warnings,
            "recommended_action": recommended_action,
            "hard_altitude_limits": {
                "min_m": self.config.altitude_hard_min_m,
                "max_m": self.config.altitude_hard_max_m,
            },
            "soft_altitude_limits": {
                "min_m": soft_min,
                "max_m": soft_max,
            },
            "telemetry_age_seconds": telemetry_age,
            "battery_level_percent": battery_level,
            "gps_fix_type": gps.get("fix_type"),
            "landing_zone": landing_zone.to_dict() if landing_zone else None,
            "remote_id": self.get_remote_id(),
            "waivers": self.get_waivers(),
        }
        evaluation["checklist"] = self._build_preflight_checklist(snapshot, evaluation)
        with self._lock:
            self._last_evaluation = evaluation
        return evaluation

    def get_preflight_checklist(self, snapshot: Optional[Dict] = None) -> Dict:
        snapshot = snapshot or self._last_snapshot or {}
        evaluation = self.evaluate_snapshot(snapshot) if snapshot else self._last_evaluation
        return self._build_preflight_checklist(snapshot, evaluation)

    def _build_preflight_checklist(self, snapshot: Dict, evaluation: Dict) -> Dict:
        items = [
            self._check_item(
                "telemetry",
                "Telemetry link is fresh",
                evaluation.get("telemetry_age_seconds") is not None
                and evaluation["telemetry_age_seconds"] <= self.config.lost_link_warn_seconds,
                detail=f"Telemetry age: {evaluation.get('telemetry_age_seconds')}",
            ),
            self._check_item(
                "geofence",
                "Companion geofence is clear",
                not evaluation.get("blockers"),
                detail="; ".join(evaluation.get("blockers") or ["No blockers detected"]),
            ),
            self._check_item(
                "battery",
                "Battery is above RTL threshold",
                (evaluation.get("battery_level_percent") or 100) > self.config.low_battery_rtl_percent,
                detail=f"Battery level: {evaluation.get('battery_level_percent')}",
            ),
            self._check_item(
                "gps",
                "GPS fix is acceptable",
                (evaluation.get("gps_fix_type") or 0) >= 3,
                detail=f"GPS fix: {evaluation.get('gps_fix_type')}",
            ),
            self._check_item(
                "remote_id",
                "Remote ID is configured",
                bool(self._remote_id.enabled and self._remote_id.operator_id),
                detail=self._remote_id.to_dict(),
            ),
            self._check_item(
                "waivers",
                "Part 107 waivers are recorded when needed",
                True,
                detail=self._waivers.to_dict(),
            ),
        ]
        passed = all(item["passed"] for item in items)
        return {
            "ready": passed,
            "items": items,
            "recommendation": evaluation.get("recommended_action") or "none",
        }

    def identify_emergency_landing_zone(self, latitude: Optional[float], longitude: Optional[float]) -> Optional[GeofenceZone]:
        landing_zones = [
            zone for zone in self._zones
            if zone.active and zone.zone_type in {"landing_zone", "emergency_landing"} and zone.polygon
        ]
        if not landing_zones:
            return None

        if latitude is None or longitude is None:
            return landing_zones[0]

        def _distance(zone: GeofenceZone) -> float:
            centroid = self._polygon_centroid(zone.polygon)
            return math.hypot(centroid[0] - longitude, centroid[1] - latitude)

        return min(landing_zones, key=_distance)

    def _find_zone_hit(self, latitude: Optional[float], longitude: Optional[float]) -> Optional[GeofenceZone]:
        if latitude is None or longitude is None:
            return None
        for zone in self._zones:
            if not zone.active or not zone.polygon:
                continue
            if self._point_in_polygon(latitude, longitude, zone.polygon):
                return zone
        return None

    def _check_item(self, item_id: str, label: str, passed: bool, detail=None) -> Dict:
        return {
            "id": item_id,
            "label": label,
            "passed": bool(passed),
            "detail": detail,
        }

    def _numeric(self, value) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _telemetry_age_seconds(self, snapshot: Dict) -> Optional[float]:
        timestamp = self._numeric(snapshot.get("timestamp"))
        if timestamp is None:
            return None
        return max(0.0, time.time() - timestamp)

    def _point_in_polygon(self, latitude: float, longitude: float, polygon: List[Dict[str, float]]) -> bool:
        points = [(float(point["longitude"]), float(point["latitude"])) for point in polygon if "latitude" in point and "longitude" in point]
        if len(points) < 3:
            return False

        inside = False
        x, y = longitude, latitude
        j = len(points) - 1
        for i in range(len(points)):
            xi, yi = points[i]
            xj, yj = points[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            )
            if intersects:
                inside = not inside
            j = i
        return inside

    def _polygon_centroid(self, polygon: List[Dict[str, float]]) -> tuple[float, float]:
        points = [(float(point["longitude"]), float(point["latitude"])) for point in polygon if "latitude" in point and "longitude" in point]
        if not points:
            return 0.0, 0.0
        lon = sum(point[0] for point in points) / len(points)
        lat = sum(point[1] for point in points) / len(points)
        return lon, lat
