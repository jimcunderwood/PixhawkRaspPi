"""High-level swarm state management."""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .database import SwarmDatabase
from .models import (
    SwarmConfig,
    SwarmFusionState,
    SwarmPeerTrust,
    SwarmRole,
    SwarmSeparationAlert,
    SwarmStatus,
    SwarmTelemetryLink,
    SwarmTelemetryLocation,
    SwarmTelemetryMessage,
    SwarmTelemetryQuality,
    SwarmTelemetryVector,
    SwarmTelemetryVehicle,
    SwarmTransportKind,
)

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_000.0


def _now() -> float:
    return time.time()


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _trust_multiplier(trust: Optional[SwarmPeerTrust]) -> float:
    return {
        SwarmPeerTrust.PRIMARY: 1.0,
        SwarmPeerTrust.TRUSTED: 0.85,
        SwarmPeerTrust.NORMAL: 0.65,
        SwarmPeerTrust.DEGRADED: 0.35,
        None: 0.65,
    }.get(trust, 0.65)


def _flatten_location(location: Dict) -> Dict[str, float]:
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    altitude = location.get("altitude")
    if latitude is None or longitude is None:
        raise ValueError("Swarm telemetry requires latitude and longitude.")
    payload = {
        "latitude": float(latitude),
        "longitude": float(longitude),
    }
    if altitude is not None:
        payload["altitude"] = float(altitude)
    return payload


def _haversine_distance_m(a: Dict[str, float], b: Dict[str, float]) -> float:
    lat1 = math.radians(float(a["latitude"]))
    lon1 = math.radians(float(a["longitude"]))
    lat2 = math.radians(float(b["latitude"]))
    lon2 = math.radians(float(b["longitude"]))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    x = dlon * math.cos((lat1 + lat2) / 2.0)
    y = dlat
    return math.sqrt((x * EARTH_RADIUS_M) ** 2 + (y * EARTH_RADIUS_M) ** 2)


class SwarmManager:
    """Keeps swarm configuration, telemetry, alerts, and fusion state in sync."""

    def __init__(
        self,
        database: SwarmDatabase,
        local_state_getter: Optional[Callable[[], Dict]] = None,
    ):
        self.database = database
        self.local_state_getter = local_state_getter
        self._lock = threading.RLock()
        self._subscribers: Dict[str, Callable] = {}
        self._sequence = 0
        self._config = self._load_or_default_config()
        self._latest_fusion_state: Optional[Dict] = self.database.get_fusion_state(self._config["swarm_id"])

    def _default_config(self) -> Dict:
        return {
            "swarm_id": "field-alpha-swarm",
            "enabled": False,
            "self_drone_id": "drone-01",
            "role": "observer",
            "transport": {
                "type": "native",
                "endpoint": "local",
            },
            "peers": [
                {
                    "drone_id": "drone-01",
                    "callsign": "Companion",
                    "role": "observer",
                    "transport": {
                        "type": "native",
                        "endpoint": "local",
                    },
                    "trust": "primary",
                    "max_age_seconds": 2.0,
                    "requires_rtk": False,
                }
            ],
            "broadcast": {
                "enabled": True,
                "rate_hz": 2.0,
                "include_location": True,
                "include_velocity": True,
                "include_quality": True,
                "include_vehicle_state": True,
                "include_alerts": True,
            },
            "fusion": {
                "mode": "weighted_gnss",
                "min_peer_count": 1,
                "max_peer_age_seconds": 2.0,
                "require_reference_node": True,
                "reference_node_id": "drone-01",
                "use_peer_velocity": True,
                "weights": {
                    "self_position": 0.7,
                    "peer_position": 0.2,
                    "peer_velocity": 0.05,
                    "heading": 0.03,
                    "quality": 0.02,
                },
            },
            "safety": {
                "min_horizontal_separation_m": 8.0,
                "min_vertical_separation_m": 3.0,
                "warn_distance_m": 15.0,
                "critical_distance_m": 8.0,
                "hold_on_loss": True,
                "hold_timeout_seconds": 3.0,
            },
        }

    def _load_or_default_config(self) -> Dict:
        config = self.database.load_config()
        if config:
            return config

        default_config = self._default_config()
        self.database.save_config(default_config)
        self.database.save_peers(default_config["swarm_id"], default_config["peers"])
        return default_config

    def get_config(self) -> Dict:
        with self._lock:
            config = self.database.load_config(self._config["swarm_id"]) or self._config
            config["peers"] = self.database.list_peers(config["swarm_id"]) or config.get("peers", [])
            self._config = config
            return config

    def validate_config(self, config: Dict) -> Dict:
        model = SwarmConfig.model_validate(config)
        return model.model_dump(mode="json")

    def update_config(self, config: Dict) -> Dict:
        validated = self.validate_config(config)
        with self._lock:
            self._config = validated
            self.database.save_config(validated)
            self.database.save_peers(validated["swarm_id"], validated["peers"])
        self.recompute_fusion()
        return validated

    def get_peers(self) -> List[Dict]:
        config = self.get_config()
        return self.database.list_peers(config["swarm_id"])

    def get_peer(self, drone_id: str) -> Optional[Dict]:
        config = self.get_config()
        return self.database.get_peer(config["swarm_id"], drone_id)

    def heartbeat_peer(self, drone_id: str, heartbeat_at: Optional[float] = None) -> Optional[Dict]:
        config = self.get_config()
        return self.database.update_peer_heartbeat(config["swarm_id"], drone_id, heartbeat_at)

    def ingest_local_snapshot(self, snapshot: Dict) -> Optional[Dict]:
        config = self.get_config()
        if not snapshot:
            return None

        message = self._build_message_from_snapshot(snapshot, config)
        self.database.record_telemetry(message)
        self.recompute_fusion()
        self._publish({"type": "swarm.telemetry", "data": message})
        return message

    def ingest_telemetry_message(self, message: Dict) -> Dict:
        validated = SwarmTelemetryMessage.model_validate(message).model_dump(mode="json")
        self.database.record_telemetry(validated)
        self.recompute_fusion()
        self._publish({"type": "swarm.telemetry", "data": validated})
        return validated

    def broadcast_local_snapshot(self, snapshot: Optional[Dict] = None) -> Optional[Dict]:
        snapshot = snapshot or (self.local_state_getter() if self.local_state_getter else None)
        if not snapshot:
            return None
        return self.ingest_local_snapshot(snapshot)

    def get_telemetry(self, seconds: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        config = self.get_config()
        return self.database.list_telemetry(config["swarm_id"], seconds=seconds, limit=limit)

    def get_alerts(self, seconds: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        config = self.get_config()
        return self.database.list_alerts(config["swarm_id"], seconds=seconds, limit=limit)

    def get_fusion_state(self) -> Optional[Dict]:
        config = self.get_config()
        state = self.database.get_fusion_state(config["swarm_id"])
        if state:
            self._latest_fusion_state = state
        return state

    def get_status(self) -> Dict:
        config = self.get_config()
        state = self.get_fusion_state()
        latest_alerts = state.get("separation_alerts", []) if state else self.get_alerts(limit=25)
        healthy_peer_count = self._healthy_peer_count(config)
        last_update = None
        if state:
            last_update = datetime.fromtimestamp(state.get("updated_at", _now()), tz=timezone.utc).isoformat()
        else:
            telemetry = self.get_telemetry(limit=1)
            if telemetry:
                last_update = datetime.fromtimestamp(float(telemetry[-1]["timestamp"]), tz=timezone.utc).isoformat()

        return SwarmStatus(
            swarm_id=config["swarm_id"],
            self_drone_id=config["self_drone_id"],
            enabled=bool(config["enabled"]),
            healthy_peer_count=healthy_peer_count,
            peer_count=len(config.get("peers", [])),
            fusion_mode=config["fusion"]["mode"],
            last_update=last_update,
            alerts=[SwarmSeparationAlert.model_validate(alert).model_dump(mode="json") for alert in latest_alerts],
        ).model_dump(mode="json")

    def get_coordination_status(self) -> Dict:
        config = self.get_config()
        telemetry = self.get_telemetry(limit=25)
        latest_by_drone: Dict[str, Dict] = {}
        for sample in telemetry:
            latest_by_drone.setdefault(sample["source_drone_id"], sample)

        peer_entries = config.get("peers", [])
        sorted_peers = sorted(
            peer_entries,
            key=lambda peer: (
                0 if peer.get("role") == "leader" else 1 if peer.get("role") == "follower" else 2,
                peer.get("drone_id") or "",
            ),
        )
        formation_mode = "leader_follower" if any(peer.get("role") == "leader" for peer in sorted_peers) else "coverage_partitioned"
        leader_peer = next((peer for peer in sorted_peers if peer.get("role") == "leader"), None)
        leader_drone_id = leader_peer.get("drone_id") if leader_peer else config["self_drone_id"]

        assignments = []
        for index, peer in enumerate(sorted_peers):
            sample = latest_by_drone.get(peer["drone_id"], {})
            assignments.append(
                {
                    "drone_id": peer["drone_id"],
                    "callsign": peer.get("callsign"),
                    "role": peer.get("role"),
                    "sector_index": index,
                    "sector_count": max(len(sorted_peers), 1),
                    "target_follow": leader_drone_id if peer.get("role") != "leader" else None,
                    "position": sample.get("location"),
                    "last_seen_at": sample.get("timestamp"),
                }
            )

        fusion = self.get_fusion_state() or self.recompute_fusion()
        nearest_peer = fusion.get("nearest_peer")
        alerts = fusion.get("separation_alerts", [])
        collision_avoidance = {
            "enabled": bool(config["safety"].get("hold_on_loss", True)),
            "nearest_peer": nearest_peer,
            "active_alerts": alerts,
            "recommended_action": (
                "hold"
                if any(alert.get("severity") == "critical" for alert in alerts)
                else "separate" if alerts
                else "continue"
            ),
        }

        return {
            "swarm_id": config["swarm_id"],
            "self_drone_id": config["self_drone_id"],
            "formation_mode": formation_mode,
            "leader_drone_id": leader_drone_id,
            "assignments": assignments,
            "collision_avoidance": collision_avoidance,
            "fusion": fusion,
            "updated_at": time.time(),
        }

    def recompute_fusion(self) -> Dict:
        with self._lock:
            config = self.get_config()
            telemetry = self.database.list_telemetry(config["swarm_id"])
            latest_by_drone: Dict[str, Dict] = {}
            for sample in telemetry:
                latest_by_drone[sample["source_drone_id"]] = sample

            self_sample = latest_by_drone.get(config["self_drone_id"])
            if self_sample is None and telemetry:
                self_sample = telemetry[-1]

            if self_sample is None:
                state = self._empty_fusion_state(config)
                self.database.record_fusion_state(state)
                self._latest_fusion_state = state
                return state

            peer_registry = {peer["drone_id"]: peer for peer in config.get("peers", [])}
            alerts: List[Dict] = []
            nearest_peer = None
            fused_location = dict(self_sample["location"])
            raw_location = dict(self_sample["location"])
            self_weight = float(config["fusion"]["weights"]["self_position"])
            total_lat = fused_location["latitude"] * max(self_weight, 0.0001)
            total_lon = fused_location["longitude"] * max(self_weight, 0.0001)
            total_alt = float(fused_location.get("altitude", 0.0)) * max(self_weight, 0.0001) if "altitude" in fused_location else 0.0
            total_weight = max(self_weight, 0.0001)

            for drone_id, sample in latest_by_drone.items():
                if drone_id == config["self_drone_id"]:
                    continue

                if not sample.get("location"):
                    continue

                peer = peer_registry.get(drone_id, {})
                max_age = min(
                    float(config["fusion"]["max_peer_age_seconds"]),
                    float(peer.get("max_age_seconds") or config["fusion"]["max_peer_age_seconds"]),
                )
                age = max(0.0, _now() - float(sample["timestamp"]))
                freshness = _clamp(1.0 - (age / max_age if max_age else 1.0))
                trust = _trust_multiplier(SwarmPeerTrust(peer["trust"]) if peer.get("trust") else None)
                quality_score = float((sample.get("quality") or {}).get("trust_score") or 0.75)
                weight = float(config["fusion"]["weights"]["peer_position"]) * freshness * trust * quality_score
                if weight <= 0:
                    continue

                lat = float(sample["location"]["latitude"])
                lon = float(sample["location"]["longitude"])
                alt = float(sample["location"].get("altitude", 0.0) or 0.0)
                total_lat += lat * weight
                total_lon += lon * weight
                total_alt += alt * weight
                total_weight += weight

                horizontal_m = _haversine_distance_m(raw_location, sample["location"])
                vertical_m = abs(float(raw_location.get("altitude", 0.0) or 0.0) - alt)
                if nearest_peer is None or horizontal_m < nearest_peer["horizontal_m"]:
                    nearest_peer = {
                        "drone_id": drone_id,
                        "horizontal_m": horizontal_m,
                        "vertical_m": vertical_m,
                        "updated_at": float(sample["timestamp"]),
                    }

                if horizontal_m <= float(config["safety"]["warn_distance_m"]):
                    severity = "critical" if horizontal_m <= float(config["safety"]["critical_distance_m"]) or vertical_m <= float(config["safety"]["min_vertical_separation_m"]) else "warning"
                    alerts.append(
                        {
                            "drone_id_a": config["self_drone_id"],
                            "drone_id_b": drone_id,
                            "horizontal_m": horizontal_m,
                            "vertical_m": vertical_m,
                            "threshold_m": float(
                                config["safety"]["critical_distance_m"]
                                if severity == "critical"
                                else config["safety"]["warn_distance_m"]
                            ),
                            "severity": severity,
                            "suggested_action": "hold" if severity == "critical" and config["safety"]["hold_on_loss"] else "separate",
                        }
                    )

            fused_location = {
                "latitude": total_lat / total_weight,
                "longitude": total_lon / total_weight,
            }
            if "altitude" in raw_location or total_alt:
                fused_location["altitude"] = total_alt / total_weight if total_weight else float(raw_location.get("altitude", 0.0) or 0.0)

            peer_count = max(0, len(latest_by_drone) - 1)
            confidence = _clamp(
                min(1.0, (total_weight / max(float(config["fusion"]["weights"]["self_position"]), 0.0001)) / max(1.0, peer_count + 1)),
                0.0,
                1.0,
            )
            if peer_count:
                confidence = _clamp(confidence + min(0.25, peer_count * 0.05), 0.0, 1.0)

            state = SwarmFusionState(
                swarm_id=config["swarm_id"],
                self_drone_id=config["self_drone_id"],
                fused_location=fused_location,
                raw_location=raw_location,
                confidence=confidence,
                peer_count=peer_count,
                reference_node_id=config["fusion"].get("reference_node_id") or (
                    config["self_drone_id"] if config["fusion"]["require_reference_node"] else None
                ),
                nearest_peer=nearest_peer,
                separation_alerts=alerts,
            ).model_dump(mode="json")
            state["updated_at"] = _now()
            self.database.record_fusion_state(state)
            self.database.record_alerts(config["swarm_id"], self_sample["sample_id"], alerts)
            self._latest_fusion_state = state
            self._publish({"type": "swarm.fusion", "data": state})
            return state

    def reset(self):
        config = self.get_config()
        self.database.clear_telemetry(config["swarm_id"])
        state = self._empty_fusion_state(config)
        state["updated_at"] = _now()
        self.database.record_fusion_state(state)
        self._latest_fusion_state = state
        self._publish({"type": "swarm.fusion", "data": state})
        return state

    def subscribe(self, client_id: str, send_callback: Callable):
        self._subscribers[client_id] = send_callback

    def unsubscribe(self, client_id: str):
        self._subscribers.pop(client_id, None)

    def _publish(self, event: Dict):
        disconnected = []
        for client_id, callback in list(self._subscribers.items()):
            try:
                callback(event)
            except Exception:
                disconnected.append(client_id)
        for client_id in disconnected:
            self.unsubscribe(client_id)

    def _healthy_peer_count(self, config: Dict) -> int:
        telemetry = self.database.list_telemetry(config["swarm_id"])
        latest_by_drone: Dict[str, Dict] = {}
        for sample in telemetry:
            latest_by_drone[sample["source_drone_id"]] = sample
        healthy = 0
        max_age = float(config["fusion"]["max_peer_age_seconds"])
        for peer in config.get("peers", []):
            sample = latest_by_drone.get(peer["drone_id"])
            if not sample:
                continue
            age = max(0.0, _now() - float(sample["timestamp"]))
            peer_max_age = float(peer.get("max_age_seconds") or max_age)
            if age <= min(max_age, peer_max_age):
                healthy += 1
        return healthy

    def _build_message_from_snapshot(self, snapshot: Dict, config: Dict) -> Dict:
        timestamp = float(snapshot.get("timestamp") or _now())
        received_at = _now()
        sequence = self._sequence + 1
        self._sequence = sequence
        sample_id = f"{config['swarm_id']}-{config['self_drone_id']}-{int(timestamp * 1000)}-{sequence:05d}"

        location = snapshot.get("location") or {}
        if not location:
            raise ValueError("Swarm telemetry requires a location snapshot.")
        location_payload = _flatten_location(location)
        if location_payload.get("altitude") is None and snapshot.get("altitude") is not None:
            location_payload["altitude"] = float(snapshot["altitude"])

        gps = snapshot.get("gps") or {}
        battery = snapshot.get("battery") or {}
        quality = SwarmTelemetryQuality(
            fix_type=gps.get("fix_type"),
            satellite_count=gps.get("satellite_count"),
            hdop=gps.get("hdop"),
            vdop=gps.get("vdop"),
            horizontal_accuracy_m=gps.get("horizontal_accuracy"),
            vertical_accuracy_m=gps.get("vertical_accuracy"),
            age_ms=max(0.0, (received_at - timestamp) * 1000.0),
            trust_score=snapshot.get("trust_score") or gps.get("trust_score"),
        ).model_dump(mode="json", exclude_none=True)

        velocity = snapshot.get("velocity") or {}
        velocity_payload = None
        if velocity or snapshot.get("ground_speed") is not None or snapshot.get("heading") is not None:
            velocity_payload = SwarmTelemetryVector(
                north_mps=velocity.get("north"),
                east_mps=velocity.get("east"),
                down_mps=velocity.get("down"),
                ground_speed_mps=snapshot.get("ground_speed"),
                heading_deg=snapshot.get("heading"),
            ).model_dump(mode="json", exclude_none=True)

        vehicle_payload = SwarmTelemetryVehicle(
            armed=snapshot.get("armed"),
            mode=snapshot.get("mode"),
            battery_percent=(battery.get("level_percent") if battery else snapshot.get("battery_percent")),
        ).model_dump(mode="json", exclude_none=True)

        transport_kind = SwarmTransportKind(config["transport"]["type"])
        link_payload = SwarmTelemetryLink(
            transport=transport_kind,
            latency_ms=snapshot.get("link", {}).get("latency_ms") if snapshot.get("link") else None,
            signal_strength_dbm=snapshot.get("link", {}).get("signal_strength_dbm") if snapshot.get("link") else None,
            packet_loss_percent=snapshot.get("link", {}).get("packet_loss_percent") if snapshot.get("link") else None,
        ).model_dump(mode="json", exclude_none=True)

        message = SwarmTelemetryMessage(
            swarm_id=config["swarm_id"],
            source_drone_id=config["self_drone_id"],
            sample_id=sample_id,
            sequence=sequence,
            timestamp=timestamp,
            received_at=received_at,
            role=SwarmRole(config["role"]),
            location=SwarmTelemetryLocation(
                latitude=location_payload["latitude"],
                longitude=location_payload["longitude"],
                altitude=location_payload.get("altitude"),
                source=location.get("source") or ("rtk" if snapshot.get("rtk") else "gps"),
                accuracy_m=location.get("accuracy_m") or gps.get("horizontal_accuracy"),
                covariance_m=location.get("covariance_m"),
            ),
            velocity=velocity_payload,
            quality=quality,
            vehicle=vehicle_payload,
            link=link_payload,
        ).model_dump(mode="json", exclude_none=True)
        return message

    def _empty_fusion_state(self, config: Dict) -> Dict:
        return {
            "swarm_id": config["swarm_id"],
            "self_drone_id": config["self_drone_id"],
            "fused_location": {"latitude": 0.0, "longitude": 0.0},
            "raw_location": None,
            "confidence": 0.0,
            "peer_count": 0,
            "reference_node_id": config["fusion"].get("reference_node_id"),
            "nearest_peer": None,
            "separation_alerts": [],
        }
