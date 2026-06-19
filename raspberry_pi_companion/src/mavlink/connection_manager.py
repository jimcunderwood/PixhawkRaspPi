"""
MAVLink Connection Manager
Handles connections to Pixhawk via serial, UDP, or TCP
Provides high-level vehicle control abstraction
"""

import collections
import collections.abc
import logging
import time
import threading
from collections import deque
from typing import Optional, Callable

# Compatibility shim for older DroneKit releases on Python 3.10+.
# DroneKit still imports `collections.MutableMapping` and similar names,
# which were moved into `collections.abc` in newer Python versions.
if not hasattr(collections, "MutableMapping"):
    collections.MutableMapping = collections.abc.MutableMapping
if not hasattr(collections, "Mapping"):
    collections.Mapping = collections.abc.Mapping
if not hasattr(collections, "Iterable"):
    collections.Iterable = collections.abc.Iterable
if not hasattr(collections, "Sequence"):
    collections.Sequence = collections.abc.Sequence

from dronekit import Command, connect, Vehicle
from pymavlink.dialects.v20 import ardupilotmega as mavutil

from ..config.settings import MAVLinkConfig, ConnectionType

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages MAVLink connection to Pixhawk"""

    def __init__(self, config: MAVLinkConfig):
        self.config = config
        self.vehicle: Optional[Vehicle] = None
        self.connected = False
        self._connection_state = "offline"
        self._connection_state_changed_at = time.time()
        self._connection_last_error = None
        self._connection_thread = None
        self._monitor_stop_event = threading.Event()
        self._monitor_active = False
        self._reconnect_backoff_seconds = 1.0
        self._max_reconnect_backoff_seconds = 30.0
        self._has_connected_once = False
        self._last_reconnect_attempt_at = None
        self._callbacks = {}
        self._lock = threading.Lock()
        self._prearm_messages = deque(maxlen=20)
        self._last_status_text = None
        self._distance_sensors = {}
        self._navigation_config_snapshot = {}
        self._obstacle_avoidance_sensor_config = {}
        self._obstacle_gpio = None
        self._obstacle_gpio_pin = None
        self._obstacle_gpio_active_low = True
        self._obstacle_gpio_available = False
        self._obstacle_gpio_last_update = None
        self._obstacle_ros_node = None
        self._obstacle_ros_thread = None
        self._obstacle_ros_available = False
        self._obstacle_ros_last_update = None
        self._obstacle_ros_last_value = None
        self._obstacle_ros_subscription = None

    def connect(self, start_monitor: bool = True) -> bool:
        """
        Establish connection to Pixhawk
        
        Returns:
            bool: True if connection successful
        """
        try:
            self._set_connection_state("connecting")
            logger.info(f"Connecting to Pixhawk via {self.config.connection_type.value}...")
            
            connection_string = self._build_connection_string()
            logger.debug(
                "MAVLink connect: %s, baud=%s, timeout=%s",
                connection_string,
                self.config.baudrate,
                self.config.timeout,
            )

            # For remote UDP-out connections PyMAVLink handles the socket semantics
            # more predictably than DroneKit's high-level connect wrapper. Create
            # a lower-level MAV connection and construct a DroneKit Vehicle from
            # it when using UDP-out so we can connect to remote SITL without
            # requiring SITL to send to the Pi's IP.
            if self.config.connection_type == ConnectionType.UDP and self.config.udp_direction in {"out", "output"}:
                from dronekit.mavlink import MAVConnection

                handler = MAVConnection(f"udpout:{self.config.udp_ip}:{self.config.udp_port}")
                handler.start()
                vehicle = Vehicle(handler)
                try:
                    vehicle.wait_ready(True, timeout=self.config.timeout)
                except Exception:
                    logger.error("Timeout in initializing connection.")
                    try:
                        vehicle.close()
                    except Exception:
                        pass
                    self.connected = False
                    return False

                self.vehicle = vehicle
            else:
                connect_kwargs = {
                    "wait_ready": True,
                    "timeout": self.config.timeout,
                }
                if self.config.connection_type == ConnectionType.SERIAL:
                    connect_kwargs["baud"] = self.config.baudrate

                self.vehicle = connect(connection_string, **connect_kwargs)

            self._register_status_text_listener()
            self._register_distance_sensor_listener()
            logger.info("Successfully connected to Pixhawk")
            self.connected = True
            self._has_connected_once = True
            self._connection_last_error = None
            self._set_connection_state("connected")
            self._reconnect_backoff_seconds = 1.0
            self._trigger_callback('connected')
            
            # Start monitoring thread
            if start_monitor:
                self._start_monitor_thread()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Pixhawk: {str(e)}")
            self.connected = False
            self._connection_last_error = str(e)
            if start_monitor or self._monitor_active:
                self._set_connection_state("reconnecting")
            else:
                self._set_connection_state("offline")
            if start_monitor and not self._monitor_active:
                self._start_monitor_thread()
            return False

    def disconnect(self):
        """Disconnect from Pixhawk"""
        self._monitor_stop_event.set()
        self._monitor_active = False
        self._disconnect_vehicle(cleanup_obstacle=True)
        self._set_connection_state("offline")
        logger.info("Disconnected from Pixhawk")

    def _disconnect_vehicle(self, cleanup_obstacle: bool = False):
        """Close the current vehicle connection without affecting monitor state."""
        if self.vehicle:
            try:
                self.vehicle.remove_message_listener('STATUSTEXT', self._handle_status_text)
            except Exception:
                pass
            try:
                self.vehicle.remove_message_listener('DISTANCE_SENSOR', self._handle_distance_sensor)
            except Exception:
                pass
            if cleanup_obstacle:
                self._cleanup_obstacle_gpio()
                self._cleanup_obstacle_ros_bridge()
            try:
                self.vehicle.close()
            except Exception:
                pass
            self.vehicle = None
        self.connected = False

    def _set_connection_state(self, state: str, error: Optional[str] = None):
        self._connection_state = state
        self._connection_state_changed_at = time.time()
        if error is not None:
            self._connection_last_error = error

    def get_connection_status(self) -> dict:
        """Return the current Pixhawk link state for API clients."""
        next_retry_in_seconds = 0.0
        if self._connection_state == "reconnecting" and self._last_reconnect_attempt_at is not None:
            elapsed = time.time() - self._last_reconnect_attempt_at
            next_retry_in_seconds = max(0.0, self._reconnect_backoff_seconds - elapsed)

        return {
            "state": self._connection_state,
            "connected": bool(self.connected),
            "monitoring": bool(self._monitor_active and not self._monitor_stop_event.is_set()),
            "reconnecting": self._connection_state == "reconnecting",
            "retry_backoff_seconds": self._reconnect_backoff_seconds
            if self._connection_state == "reconnecting"
            else 0.0,
            "max_retry_backoff_seconds": self._max_reconnect_backoff_seconds,
            "next_retry_in_seconds": next_retry_in_seconds,
            "last_reconnect_attempt_at": self._last_reconnect_attempt_at,
            "last_changed_at": self._connection_state_changed_at,
            "last_error": self._connection_last_error,
        }

    def _build_connection_string(self) -> str:
        """Build DroneKit connection string based on config"""
        if self.config.connection_type == ConnectionType.SERIAL:
            return f"{self.config.port}"

        if self.config.connection_type == ConnectionType.UDP:
            direction = self.config.udp_direction
            if direction in {"in", "input"}:
                return f"udpin:{self.config.udp_ip}:{self.config.udp_port}"
            if direction in {"out", "output"}:
                return f"udpout:{self.config.udp_ip}:{self.config.udp_port}"
            raise ValueError(f"Unknown UDP direction: {direction}. Use 'in' for local bind or 'out' for remote connect.")

        if self.config.connection_type == ConnectionType.TCP:
            return f"tcp:{self.config.udp_ip}:{self.config.udp_port}"

        raise ValueError(f"Unknown connection type: {self.config.connection_type}")

    def _register_status_text_listener(self):
        """Track autopilot status text, including ArduPilot pre-arm failures."""
        if not self.vehicle:
            return

        try:
            self.vehicle.add_message_listener('STATUSTEXT', self._handle_status_text)
        except Exception as e:
            logger.warning(f"Unable to register STATUSTEXT listener: {str(e)}")

    def _register_distance_sensor_listener(self):
        """Track live DISTANCE_SENSOR MAVLink updates for each Pixhawk rangefinder."""
        if not self.vehicle:
            return

        try:
            self.vehicle.add_message_listener('DISTANCE_SENSOR', self._handle_distance_sensor)
        except Exception as e:
            logger.warning(f"Unable to register DISTANCE_SENSOR listener: {str(e)}")

    def _handle_status_text(self, vehicle, name, message):
        """Store recent STATUSTEXT messages that explain pre-arm readiness."""
        try:
            text = getattr(message, "text", "")
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            text = str(text).strip().rstrip("\x00")
            if not text:
                return

            entry = {
                "timestamp": time.time(),
                "severity": getattr(message, "severity", None),
                "text": text,
            }

            with self._lock:
                self._last_status_text = entry
                lowered = text.lower()
                if "prearm" in lowered or "pre-arm" in lowered:
                    self._prearm_messages.append(entry)
        except Exception as e:
            logger.debug(f"Failed to process STATUSTEXT message: {str(e)}")

    def _handle_distance_sensor(self, vehicle, name, message):
        """Store the latest MAVLink distance sensor reading."""
        try:
            sensor_data = self._normalize_distance_sensor_message(message)
            if not sensor_data:
                return

            sensor_id = sensor_data.get("sensor_id")
            cache_key = sensor_id
            if cache_key is None:
                cache_key = f"orientation:{sensor_data.get('orientation')}:{sensor_data.get('timestamp')}"

            with self._lock:
                self._distance_sensors[cache_key] = sensor_data
        except Exception as e:
            logger.debug(f"Failed to process DISTANCE_SENSOR message: {str(e)}")

    def _normalize_distance_sensor_message(self, message) -> dict:
        """Convert a MAVLink DISTANCE_SENSOR message to a cached status record."""
        current_distance_cm = getattr(message, "current_distance", None)
        min_distance_cm = getattr(message, "min_distance", None)
        max_distance_cm = getattr(message, "max_distance", None)

        def _cm_to_meters(value):
            if value is None:
                return None
            try:
                return float(value) / 100.0
            except (TypeError, ValueError):
                return None

        return {
            "timestamp": time.time(),
            "time_boot_ms": getattr(message, "time_boot_ms", None),
            "sensor_id": getattr(message, "id", None),
            "orientation": getattr(message, "orientation", None),
            "type": getattr(message, "type", None),
            "current_distance_meters": _cm_to_meters(current_distance_cm),
            "current_distance_cm": current_distance_cm,
            "min_distance_meters": _cm_to_meters(min_distance_cm),
            "max_distance_meters": _cm_to_meters(max_distance_cm),
            "covariance_cm2": getattr(message, "covariance", None),
            "horizontal_fov": getattr(message, "horizontal_fov", None),
            "vertical_fov": getattr(message, "vertical_fov", None),
            "quaternion": getattr(message, "quaternion", None),
            "signal_quality": getattr(message, "signal_quality", None),
        }

    def _start_monitor_thread(self):
        """Start background thread to monitor connection health"""
        if self._connection_thread and self._connection_thread.is_alive():
            return

        self._monitor_stop_event.clear()
        self._monitor_active = True
        self._connection_thread = threading.Thread(
            target=self._monitor_connection,
            daemon=True
        )
        self._connection_thread.start()

    def _monitor_connection(self):
        """Monitor connection and detect disconnections"""
        while self._monitor_active and not self._monitor_stop_event.is_set():
            try:
                if self._vehicle_connection_healthy():
                    self._reconnect_backoff_seconds = 1.0
                    if self.connected:
                        self._set_connection_state("connected")
                    time.sleep(1)
                    continue

                if self.vehicle or self.connected:
                    logger.warning("Pixhawk connection lost; closing connection and scheduling reconnect.")
                    self._disconnect_vehicle(cleanup_obstacle=False)
                    self._trigger_callback('disconnected')
                    self._set_connection_state("reconnecting")

                if self._monitor_stop_event.wait(self._reconnect_backoff_seconds):
                    break

                self._set_connection_state("reconnecting")
                self._last_reconnect_attempt_at = time.time()
                if self.connect(start_monitor=False):
                    logger.info("Reconnected to Pixhawk")
                    self._reconnect_backoff_seconds = 1.0
                    self._set_connection_state("connected")
                    continue

                self._reconnect_backoff_seconds = min(
                    self._reconnect_backoff_seconds * 2,
                    self._max_reconnect_backoff_seconds,
                ) if self._has_connected_once else 1.0
                self._set_connection_state("reconnecting")
            except Exception as e:
                logger.warning(f"Connection health check failed: {str(e)}")
                self._disconnect_vehicle(cleanup_obstacle=False)
                self._trigger_callback('disconnected')
                self._set_connection_state("reconnecting", error=str(e))
                self._last_reconnect_attempt_at = time.time()
                if self._monitor_stop_event.wait(self._reconnect_backoff_seconds):
                    break
                self._reconnect_backoff_seconds = min(
                    self._reconnect_backoff_seconds * 2,
                    self._max_reconnect_backoff_seconds,
                ) if self._has_connected_once else 1.0

    def _vehicle_connection_healthy(self) -> bool:
        if not self.vehicle:
            return False

        try:
            heartbeat_age = getattr(self.vehicle, "last_heartbeat", None)
            if heartbeat_age is None:
                return True

            heartbeat_timeout = max(5.0, min(float(self.config.timeout), 10.0))
            return float(heartbeat_age) <= heartbeat_timeout
        except Exception:
            return False

    # Vehicle Control Methods

    def arm(self) -> bool:
        """Arm the drone"""
        try:
            if not self.vehicle:
                logger.error("Vehicle not connected")
                return False
            
            if self.vehicle.is_armed:
                logger.warning("Vehicle already armed")
                return True
            
            self.vehicle.armed = True
            
            # Wait for arming
            for _ in range(100):
                if self.vehicle.armed:
                    logger.info("Vehicle armed successfully")
                    self._trigger_callback('armed')
                    return True
                time.sleep(0.1)
            
            logger.error("Arming timeout")
            return False
            
        except Exception as e:
            logger.error(f"Failed to arm vehicle: {str(e)}")
            return False

    def disarm(self) -> bool:
        """Disarm the drone"""
        try:
            if not self.vehicle:
                logger.error("Vehicle not connected")
                return False
            
            self.vehicle.armed = False
            
            for _ in range(100):
                if not self.vehicle.armed:
                    logger.info("Vehicle disarmed successfully")
                    self._trigger_callback('disarmed')
                    return True
                time.sleep(0.1)
            
            logger.error("Disarming timeout")
            return False
            
        except Exception as e:
            logger.error(f"Failed to disarm vehicle: {str(e)}")
            return False

    def takeoff(self, altitude: float) -> bool:
        """
        Takeoff to specified altitude
        
        Args:
            altitude: Target altitude in meters
            
        Returns:
            bool: Success status
        """
        try:
            if not self.vehicle:
                logger.error("Vehicle not connected")
                return False
            
            if not self.vehicle.is_armable:
                logger.error("Vehicle is not armable")
                return False
            
            # Arm if not already armed
            if not self.vehicle.armed:
                if not self.arm():
                    return False
            
            # Set to GUIDED mode for autonomous control
            self.set_mode("GUIDED")
            
            # Issue takeoff command
            self.vehicle.simple_takeoff(altitude)
            
            logger.info(f"Takeoff initiated to {altitude}m")
            self._trigger_callback('takeoff', {'altitude': altitude})
            
            return True
            
        except Exception as e:
            logger.error(f"Takeoff failed: {str(e)}")
            return False

    def land(self) -> bool:
        """Land the drone"""
        try:
            if not self.vehicle:
                logger.error("Vehicle not connected")
                return False
            
            self.set_mode("LAND")
            logger.info("Landing initiated")
            self._trigger_callback('landing')
            
            return True
            
        except Exception as e:
            logger.error(f"Landing failed: {str(e)}")
            return False

    def set_mode(self, mode: str) -> bool:
        """
        Set flight mode
        
        Args:
            mode: Flight mode (GUIDED, AUTO, LOITER, LAND, etc.)
            
        Returns:
            bool: Success status
        """
        try:
            if not self.vehicle:
                logger.error("Vehicle not connected")
                return False
            
            self.vehicle.mode = self.vehicle.mode.__class__(mode)
            
            for _ in range(50):
                if self.vehicle.mode.name == mode:
                    logger.info(f"Mode set to {mode}")
                    self._trigger_callback('mode_changed', {'mode': mode})
                    return True
                time.sleep(0.1)
            
            logger.warning(f"Mode change to {mode} may not have succeeded")
            return False
            
        except Exception as e:
            logger.error(f"Failed to set mode: {str(e)}")
            return False

    def goto_location(self, latitude: float, longitude: float, altitude: float) -> bool:
        """
        Fly to specific GPS location
        
        Args:
            latitude: Target latitude
            longitude: Target longitude
            altitude: Target altitude in meters
            
        Returns:
            bool: Success status
        """
        try:
            if not self.vehicle:
                logger.error("Vehicle not connected")
                return False
            
            from dronekit import LocationGlobal
            
            location = LocationGlobal(latitude, longitude, altitude)
            self.vehicle.simple_goto(location)
            
            logger.info(f"Flying to {latitude}, {longitude} at {altitude}m")
            self._trigger_callback('goto', {
                'lat': latitude,
                'lon': longitude,
                'alt': altitude
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Goto failed: {str(e)}")
            return False

    def set_airspeed(self, airspeed: float) -> bool:
        """Set target airspeed"""
        try:
            if not self.vehicle:
                return False
            
            self.vehicle.airspeed = airspeed
            logger.info(f"Airspeed set to {airspeed} m/s")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to set airspeed: {str(e)}")
            return False

    def set_groundspeed(self, groundspeed: float) -> bool:
        """Set target groundspeed"""
        try:
            if not self.vehicle:
                return False
            
            self.vehicle.groundspeed = groundspeed
            logger.info(f"Groundspeed set to {groundspeed} m/s")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to set groundspeed: {str(e)}")
            return False

    # Navigation Feature Configuration

    def apply_navigation_config(self, navigation_config) -> dict:
        """Apply companion obstacle avoidance and terrain-following settings to Pixhawk parameters."""
        config_data = (
            navigation_config.to_dict()
            if hasattr(navigation_config, "to_dict")
            else navigation_config
        )
        self._navigation_config_snapshot = dict(config_data or {})
        self._configure_obstacle_avoidance_runtime((config_data or {}).get("obstacle_avoidance", {}))
        if not self.vehicle:
            return {
                "success": False,
                "message": "Vehicle not connected.",
                "applied": [],
                "failed": [],
            }
        updates = self._navigation_parameter_updates(config_data or {})
        applied = []
        failed = []

        for name, value in updates.items():
            try:
                self.vehicle.parameters[name] = value
                applied.append({"name": name, "value": value})
            except Exception as e:
                logger.error(f"Failed to set Pixhawk parameter {name}: {str(e)}")
                failed.append({"name": name, "value": value, "error": str(e)})

        return {
            "success": not failed,
            "message": "Navigation parameters applied" if not failed else "Some parameters failed to apply.",
            "applied": applied,
            "failed": failed,
            "requested": config_data,
            "status": self.get_navigation_status(),
        }

    def get_navigation_status(self) -> dict:
        """Return current Pixhawk navigation-related parameter and sensor status."""
        return {
            "obstacle_avoidance": {
                "parameters": self._parameter_snapshot(
                    [
                        "AVOID_ENABLE",
                        "AVOID_MARGIN",
                        "AVOID_BEHAVE",
                        "AVOID_BACKUP_SPD",
                        "AVOID_ALT_MIN",
                        "PRX1_TYPE",
                        "OA_TYPE",
                        "OA_BR_LOOKAHEAD",
                        "OA_MARGIN_MAX",
                        "OA_BR_TYPE",
                        "OA_DB_SIZE",
                    ]
                ),
                "proximity": self._proximity_status(),
                "sensor": self._obstacle_avoidance_status(),
            },
            "terrain_following": {
                "parameters": self._parameter_snapshot(
                    [
                        "TERRAIN_ENABLE",
                        "TERRAIN_SPACING",
                        "TERRAIN_CACHE_SZ",
                        "WP_RFND_USE",
                        "RTL_ALT_TYPE",
                    ]
                ),
                "terrain": self._terrain_status(),
                "hooks": self._terrain_hooks_status(),
            },
            "distance_sensors": self._distance_sensor_snapshot(),
        }

    def _navigation_parameter_updates(self, navigation_config: dict) -> dict:
        updates = {}
        updates.update(
            self._obstacle_avoidance_parameter_updates(
                navigation_config.get("obstacle_avoidance", {})
            )
        )
        updates.update(
            self._terrain_following_parameter_updates(
                navigation_config.get("terrain_following", {})
            )
        )
        return updates

    def _obstacle_avoidance_parameter_updates(self, obstacle_config: dict) -> dict:
        enabled = bool(obstacle_config.get("enabled", False))
        mode = str(obstacle_config.get("mode", "simple")).strip().lower()
        if not enabled or mode == "disabled":
            return {
                "AVOID_ENABLE": 0,
                "OA_TYPE": 0,
            }

        updates = {
            "AVOID_ENABLE": 7,
            "AVOID_MARGIN": float(obstacle_config.get("margin_meters", 2.0)),
            "AVOID_BEHAVE": self._avoidance_behavior_value(
                obstacle_config.get("behavior", "slide")
            ),
            "AVOID_BACKUP_SPD": float(obstacle_config.get("backup_speed_mps", 0.0)),
            "AVOID_ALT_MIN": float(obstacle_config.get("min_altitude_meters", 0.0)),
        }

        proximity_type = obstacle_config.get("proximity_type")
        if proximity_type is not None:
            updates["PRX1_TYPE"] = int(proximity_type)

        if mode == "bendy_ruler":
            updates.update(
                {
                    "OA_TYPE": 1,
                    "OA_BR_LOOKAHEAD": float(obstacle_config.get("lookahead_meters", 5.0)),
                    "OA_MARGIN_MAX": float(obstacle_config.get("margin_meters", 2.0)),
                    "OA_BR_TYPE": self._bendy_ruler_type_value(
                        obstacle_config.get("bendy_ruler_type", "horizontal")
                    ),
                }
            )
            obstacle_database_size = obstacle_config.get("obstacle_database_size")
            if obstacle_database_size is not None:
                updates["OA_DB_SIZE"] = int(obstacle_database_size)
        else:
            updates["OA_TYPE"] = 0

        return updates

    def _terrain_following_parameter_updates(self, terrain_config: dict) -> dict:
        enabled = bool(terrain_config.get("enabled", False))
        source = str(terrain_config.get("source", "rangefinder")).strip().lower()
        if not enabled:
            return {
                "WP_RFND_USE": 0,
                "RTL_ALT_TYPE": 0,
            }

        updates = {}
        if source == "terrain_database":
            updates["TERRAIN_ENABLE"] = 1
        if source == "rangefinder" or terrain_config.get("use_rangefinder_for_waypoints", True):
            updates["WP_RFND_USE"] = 1
        else:
            updates["WP_RFND_USE"] = 0
        if terrain_config.get("rtl_terrain_enabled", False):
            updates["RTL_ALT_TYPE"] = 1

        terrain_spacing = terrain_config.get("terrain_spacing_meters")
        if terrain_spacing is not None:
            updates["TERRAIN_SPACING"] = float(terrain_spacing)

        return updates

    def _avoidance_behavior_value(self, behavior) -> int:
        return 1 if str(behavior).strip().lower() == "slide" else 0

    def _bendy_ruler_type_value(self, bendy_ruler_type) -> int:
        return 2 if str(bendy_ruler_type).strip().lower() == "vertical" else 1

    def _parameter_snapshot(self, names: list) -> dict:
        return {name: self._get_parameter(name) for name in names}

    def _get_parameter(self, name: str):
        if not self.vehicle:
            return None
        try:
            return self.vehicle.parameters.get(name)
        except Exception:
            try:
                return self.vehicle.parameters[name]
            except Exception:
                return None

    def _proximity_status(self) -> dict:
        sensor = self._obstacle_mavlink_status()
        if sensor:
            return sensor

        proximity = getattr(self.vehicle, "proximity", None) if self.vehicle else None
        if proximity:
            return {
                "available": True,
                "source": "vehicle.proximity",
                "distance_meters": getattr(proximity, "distance", None),
            }

        return {
            "available": False,
            "source": None,
        }

    # Mission Management

    def upload_mission(self, mission_items: list) -> dict:
        """Upload companion mission items to the Pixhawk."""
        if not self.vehicle:
            return {"success": False, "message": "Vehicle not connected.", "uploaded_count": 0}

        try:
            commands = self.vehicle.commands
            commands.clear()
            commands.wait_ready()

            uploaded_count = 0
            skipped_items = []
            for item in mission_items:
                command = self._mission_item_to_command(item)
                if command is None:
                    skipped_items.append(item.to_dict() if hasattr(item, "to_dict") else str(item))
                    continue
                commands.add(command)
                uploaded_count += 1

            commands.upload()
            commands.wait_ready()
            return {
                "success": True,
                "uploaded_count": uploaded_count,
                "skipped_count": len(skipped_items),
                "skipped_items": skipped_items,
                "pixhawk_count": len(commands),
                "checksum": self._mission_checksum([self._command_to_dict(cmd, index) for index, cmd in enumerate(commands)]),
            }
        except Exception as e:
            logger.error(f"Mission upload failed: {str(e)}")
            return {"success": False, "message": str(e), "uploaded_count": 0}

    def download_mission(self) -> dict:
        """Download mission commands from the Pixhawk."""
        if not self.vehicle:
            return {"success": False, "message": "Vehicle not connected.", "items": []}

        try:
            commands = self.vehicle.commands
            commands.download()
            commands.wait_ready()
            items = [self._command_to_dict(command, index) for index, command in enumerate(commands)]
            return {
                "success": True,
                "count": len(items),
                "items": items,
                "checksum": self._mission_checksum(items),
            }
        except Exception as e:
            logger.error(f"Mission download failed: {str(e)}")
            return {"success": False, "message": str(e), "items": []}

    def clear_pixhawk_mission(self) -> dict:
        """Clear mission commands on the Pixhawk."""
        if not self.vehicle:
            return {"success": False, "message": "Vehicle not connected."}

        try:
            commands = self.vehicle.commands
            commands.clear()
            commands.upload()
            commands.wait_ready()
            return {"success": True, "pixhawk_count": len(commands)}
        except Exception as e:
            logger.error(f"Mission clear failed: {str(e)}")
            return {"success": False, "message": str(e)}

    def verify_mission(self, expected_items: list) -> dict:
        """Compare companion mission items with Pixhawk mission count/checksum."""
        downloaded = self.download_mission()
        if not downloaded.get("success"):
            return downloaded

        expected_commands = []
        skipped_items = []
        for item in expected_items:
            command = self._mission_item_to_command(item)
            if command is None:
                skipped_items.append(item.to_dict() if hasattr(item, "to_dict") else str(item))
                continue
            expected_commands.append(self._command_to_dict(command, len(expected_commands)))

        expected_checksum = self._mission_checksum(expected_commands)
        return {
            "success": True,
            "matches": (
                len(expected_commands) == downloaded["count"]
                and expected_checksum == downloaded["checksum"]
            ),
            "expected_count": len(expected_commands),
            "pixhawk_count": downloaded["count"],
            "expected_checksum": expected_checksum,
            "pixhawk_checksum": downloaded["checksum"],
            "skipped_count": len(skipped_items),
            "skipped_items": skipped_items,
        }

    def _mission_item_to_command(self, item):
        """Convert internal mission item to DroneKit Command."""
        from ..missions.planner import MissionItemType

        command_map = {
            MissionItemType.WAYPOINT: mavutil.MAV_CMD_NAV_WAYPOINT,
            MissionItemType.LOITER: mavutil.MAV_CMD_NAV_LOITER_TURNS,
            MissionItemType.LAND: mavutil.MAV_CMD_NAV_LAND,
            MissionItemType.TAKEOFF: mavutil.MAV_CMD_NAV_TAKEOFF,
            MissionItemType.SPRAY_START: mavutil.MAV_CMD_DO_SET_RELAY,
            MissionItemType.SPRAY_STOP: mavutil.MAV_CMD_DO_SET_RELAY,
        }
        command_id = command_map.get(item.type)
        if command_id is None:
            return None

        x = item.location.latitude
        y = item.location.longitude
        z = item.location.altitude
        param1 = item.param1
        param2 = item.param2
        param3 = item.param3
        param4 = item.param4
        altitude_frame = getattr(getattr(item, "altitude_frame", None), "value", None)
        if altitude_frame is None:
            altitude_frame = getattr(item, "altitude_frame", "relative")
        frame = (
            mavutil.MAV_FRAME_GLOBAL_TERRAIN_ALT
            if altitude_frame == "terrain"
            else mavutil.MAV_FRAME_GLOBAL_RELATIVE_ALT
        )

        if item.type == MissionItemType.SPRAY_START:
            param1, param2, x, y, z = 0, 1, 0, 0, 0
        elif item.type == MissionItemType.SPRAY_STOP:
            param1, param2, x, y, z = 0, 0, 0, 0, 0

        return Command(
            0,
            0,
            0,
            frame,
            command_id,
            0,
            1,
            param1,
            param2,
            param3,
            param4,
            x,
            y,
            z,
        )

    def _command_to_dict(self, command, sequence: int) -> dict:
        return {
            "sequence": sequence,
            "command": getattr(command, "command", None),
            "frame": getattr(command, "frame", None),
            "current": getattr(command, "current", None),
            "autocontinue": getattr(command, "autocontinue", None),
            "param1": getattr(command, "param1", None),
            "param2": getattr(command, "param2", None),
            "param3": getattr(command, "param3", None),
            "param4": getattr(command, "param4", None),
            "location": {
                "latitude": getattr(command, "x", None),
                "longitude": getattr(command, "y", None),
                "altitude": getattr(command, "z", None),
            },
        }

    def _mission_checksum(self, items: list) -> str:
        import hashlib
        import json

        normalized = json.dumps(items, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # Callback Management

    def register_callback(self, event: str, callback: Callable):
        """
        Register event callback
        
        Args:
            event: Event name (connected, disconnected, armed, etc.)
            callback: Callback function
        """
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _trigger_callback(self, event: str, data=None):
        """Trigger all callbacks for an event"""
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    if data:
                        callback(data)
                    else:
                        callback()
                except Exception as e:
                    logger.error(f"Error in callback for {event}: {str(e)}")

    # Telemetry Access

    def _gps_status(self) -> Optional[dict]:
        gps = getattr(self.vehicle, "gps_0", None) if self.vehicle else None
        if not gps:
            return None

        fix_type = getattr(gps, "fix_type", None)
        return {
            "fix_type": fix_type,
            "fix_name": self._gps_fix_name(fix_type),
            "satellite_count": getattr(gps, "satellites_visible", None),
            "horizontal_accuracy": getattr(gps, "eph", None),
            "vertical_accuracy": getattr(gps, "epv", None),
        }

    def _rtk_status(self, gps_status: Optional[dict]) -> dict:
        fix_type = (gps_status or {}).get("fix_type")
        return {
            "enabled_by_fix": fix_type in {5, 6},
            "fix_type": fix_type,
            "fix_name": (gps_status or {}).get("fix_name"),
            "is_float": fix_type == 5,
            "is_fixed": fix_type == 6,
        }

    def _gps_fix_name(self, fix_type: Optional[int]) -> Optional[str]:
        return {
            0: "no_gps",
            1: "no_fix",
            2: "2d_fix",
            3: "3d_fix",
            4: "dgps",
            5: "rtk_float",
            6: "rtk_fixed",
        }.get(fix_type)

    def _terrain_status(self) -> dict:
        sensor = self._selected_distance_sensor(role="terrain_following")
        if sensor:
            return {
                "available": True,
                "source": "mavlink.distance_sensor",
                "sensor_id": sensor.get("sensor_id"),
                "orientation": sensor.get("orientation"),
                "rangefinder_distance_meters": sensor.get("current_distance_meters"),
                "rangefinder_voltage": None,
                "min_distance_meters": sensor.get("min_distance_meters"),
                "max_distance_meters": sensor.get("max_distance_meters"),
                "signal_quality": sensor.get("signal_quality"),
                "updated_at": sensor.get("timestamp"),
            }

        rangefinder = getattr(self.vehicle, "rangefinder", None) if self.vehicle else None
        terrain = {
            "available": False,
            "rangefinder_distance_meters": None,
            "rangefinder_voltage": None,
            "source": None,
        }

        if rangefinder:
            terrain.update(
                {
                    "available": True,
                    "rangefinder_distance_meters": getattr(rangefinder, "distance", None),
                    "rangefinder_voltage": getattr(rangefinder, "voltage", None),
                    "source": "vehicle.rangefinder",
                }
            )

        return terrain

    def _terrain_hooks_status(self) -> dict:
        terrain_config = dict(self._navigation_config_snapshot.get("terrain_following", {}))
        return {
            "ros_bridge_enabled": bool(terrain_config.get("ros_bridge_enabled", False)),
            "ros_backend": terrain_config.get("ros_backend", "mavros"),
            "ros_topic": terrain_config.get("ros_topic"),
            "mavros_topic": terrain_config.get("mavros_topic"),
            "ros_frame_id": terrain_config.get("ros_frame_id"),
        }

    def _distance_sensor_snapshot(self) -> list:
        with self._lock:
            sensors = list(self._distance_sensors.values())

        sensors.sort(key=lambda sensor: (sensor.get("timestamp") or 0.0, sensor.get("sensor_id") is None))
        return [
            {
                "sensor_id": sensor.get("sensor_id"),
                "orientation": sensor.get("orientation"),
                "distance_meters": sensor.get("current_distance_meters"),
                "min_distance_meters": sensor.get("min_distance_meters"),
                "max_distance_meters": sensor.get("max_distance_meters"),
                "signal_quality": sensor.get("signal_quality"),
                "updated_at": sensor.get("timestamp"),
                "source": "mavlink.distance_sensor",
            }
            for sensor in sensors
        ]

    def _selected_distance_sensor(self, role: str) -> Optional[dict]:
        preferred_sensor_id = self._preferred_sensor_id(role)
        return self._selected_distance_sensor_by_id(preferred_sensor_id)

    def _preferred_sensor_id(self, role: str) -> Optional[int]:
        if role == "terrain_following":
            return 0

        if role == "obstacle_avoidance":
            sensor_config = self._obstacle_avoidance_sensor_config or {}
            sensor_id = sensor_config.get("mavlink_sensor_id")
            if sensor_id is not None:
                try:
                    return int(sensor_id)
                except (TypeError, ValueError):
                    return None

        return None

    def _selected_distance_sensor_by_id(self, preferred_sensor_id: Optional[int]) -> Optional[dict]:
        with self._lock:
            sensors = list(self._distance_sensors.values())

        if not sensors:
            return None

        sensors = [sensor for sensor in sensors if sensor.get("current_distance_meters") is not None]
        if not sensors:
            return None

        if preferred_sensor_id is not None:
            matched = [sensor for sensor in sensors if sensor.get("sensor_id") == preferred_sensor_id]
            if matched:
                return max(matched, key=lambda sensor: sensor.get("timestamp") or 0.0)

        preferred_orientation = None
        if preferred_sensor_id is None:
            preferred_orientation = self._sensor_orientation_for_role("terrain_following")
        if preferred_orientation is not None:
            oriented = [sensor for sensor in sensors if sensor.get("orientation") == preferred_orientation]
            if oriented:
                return max(oriented, key=lambda sensor: sensor.get("timestamp") or 0.0)

        return max(sensors, key=lambda sensor: sensor.get("timestamp") or 0.0)

    def _sensor_orientation_for_role(self, role: str) -> Optional[int]:
        parameter_name = {
            "terrain_following": "RNGFND1_ORIENT",
        }.get(role)
        if not parameter_name:
            return None

        orientation = self._get_parameter(parameter_name)
        if orientation is None:
            return None

        try:
            return int(orientation)
        except (TypeError, ValueError):
            return None

    def _configure_obstacle_avoidance_runtime(self, obstacle_config: dict):
        config_snapshot = dict(obstacle_config or {})
        self._obstacle_avoidance_sensor_config = config_snapshot
        source = str(config_snapshot.get("source", "mavlink")).strip().lower()
        if source == "gpio":
            self._initialize_obstacle_gpio(config_snapshot)
        else:
            self._cleanup_obstacle_gpio()
        if source == "ros" or bool(config_snapshot.get("ros_enabled", False)):
            self._initialize_obstacle_ros_bridge(config_snapshot)
        else:
            self._cleanup_obstacle_ros_bridge()

    def _initialize_obstacle_gpio(self, obstacle_config: dict):
        gpio_pin = obstacle_config.get("gpio_pin")
        if gpio_pin is None:
            self._cleanup_obstacle_gpio()
            return

        try:
            gpio_pin = int(gpio_pin)
        except (TypeError, ValueError):
            self._cleanup_obstacle_gpio()
            return

        if self._obstacle_gpio and self._obstacle_gpio_pin == gpio_pin:
            self._obstacle_gpio_active_low = bool(obstacle_config.get("gpio_active_low", True))
            self._obstacle_gpio_available = True
            return

        self._cleanup_obstacle_gpio()
        try:
            import RPi.GPIO as GPIO
            self._obstacle_gpio = GPIO
            self._obstacle_gpio.setmode(GPIO.BCM)
            self._obstacle_gpio.setup(gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._obstacle_gpio_pin = gpio_pin
            self._obstacle_gpio_active_low = bool(obstacle_config.get("gpio_active_low", True))
            self._obstacle_gpio_available = True
            logger.info("Obstacle avoidance GPIO sensor initialized on pin %s", gpio_pin)
        except ImportError:
            logger.warning("RPi.GPIO not available - obstacle avoidance GPIO sensor disabled")
            self._cleanup_obstacle_gpio()
        except Exception as e:
            logger.error(f"Failed to initialize obstacle avoidance GPIO pin {gpio_pin}: {str(e)}")
            self._cleanup_obstacle_gpio()

    def _cleanup_obstacle_gpio(self):
        try:
            if self._obstacle_gpio and self._obstacle_gpio_pin is not None:
                self._obstacle_gpio.cleanup(self._obstacle_gpio_pin)
        except Exception:
            pass
        self._obstacle_gpio = None
        self._obstacle_gpio_pin = None
        self._obstacle_gpio_available = False
        self._obstacle_gpio_last_update = None

    def _initialize_obstacle_ros_bridge(self, obstacle_config: dict):
        ros_enabled = bool(obstacle_config.get("ros_enabled", False))
        ros_topic = str(obstacle_config.get("ros_topic", "")).strip()
        ros_message_type = str(obstacle_config.get("ros_message_type", "std_msgs/Float32")).strip()
        if not ros_enabled or not ros_topic or not ros_message_type:
            self._cleanup_obstacle_ros_bridge()
            return

        if self._obstacle_ros_node and self._obstacle_ros_available:
            return

        self._cleanup_obstacle_ros_bridge()
        try:
            import importlib

            rclpy = importlib.import_module("rclpy")
            node_module = importlib.import_module("rclpy.node")
            message_class = self._load_ros_message_type(ros_message_type)
            if message_class is None:
                logger.warning("Unsupported ROS obstacle message type: %s", ros_message_type)
                return

            rclpy.init(args=None)

            parent = self

            class _ObstacleAvoidanceRosNode(node_module.Node):
                def __init__(self):
                    super().__init__("drone_companion_obstacle_avoidance")
                    self.create_subscription(message_class, ros_topic, self._callback, 10)

                def _callback(self, message):
                    parent._obstacle_ros_last_update = time.time()
                    parent._obstacle_ros_last_value = parent._extract_ros_distance_value(message)

            self._obstacle_ros_node = _ObstacleAvoidanceRosNode()
            self._obstacle_ros_available = True

            def _spin():
                try:
                    rclpy.spin(self._obstacle_ros_node)
                except Exception as e:
                    logger.warning("ROS obstacle avoidance bridge stopped: %s", str(e))
                finally:
                    try:
                        if self._obstacle_ros_node:
                            self._obstacle_ros_node.destroy_node()
                    except Exception:
                        pass
                    try:
                        if rclpy.ok():
                            rclpy.shutdown()
                    except Exception:
                        pass
                    self._obstacle_ros_available = False

            self._obstacle_ros_thread = threading.Thread(target=_spin, daemon=True)
            self._obstacle_ros_thread.start()
            logger.info("Obstacle avoidance ROS bridge initialized on topic %s", ros_topic)
        except Exception as e:
            logger.warning("ROS obstacle avoidance bridge unavailable: %s", str(e))
            self._cleanup_obstacle_ros_bridge()

    def _cleanup_obstacle_ros_bridge(self):
        rclpy = None
        try:
            try:
                import importlib
                rclpy = importlib.import_module("rclpy")
            except Exception:
                rclpy = None
            if self._obstacle_ros_node is not None:
                try:
                    self._obstacle_ros_node.destroy_node()
                except Exception:
                    pass
            if rclpy is not None:
                try:
                    if rclpy.ok():
                        rclpy.shutdown()
                except Exception:
                    pass
        finally:
            thread = self._obstacle_ros_thread
            self._obstacle_ros_node = None
            self._obstacle_ros_thread = None
            self._obstacle_ros_available = False
            self._obstacle_ros_last_update = None
            self._obstacle_ros_last_value = None
            self._obstacle_ros_subscription = None
            if thread and thread.is_alive():
                try:
                    thread.join(timeout=2)
                except Exception:
                    pass

    def _load_ros_message_type(self, ros_message_type: str):
        try:
            package, message = ros_message_type.split("/", 1)
            module = __import__(f"{package}.msg", fromlist=[message])
            return getattr(module, message, None)
        except Exception:
            return None

    def _extract_ros_distance_value(self, message) -> Optional[float]:
        for field in ("distance", "range", "data", "current_distance", "current_distance_meters"):
            value = getattr(message, field, None)
            if value is not None:
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if field == "current_distance" and numeric > 100.0:
                    return numeric / 100.0
                return numeric
        return None

    def _obstacle_mavlink_status(self) -> Optional[dict]:
        sensor_config = self._obstacle_avoidance_sensor_config or {}
        source = str(sensor_config.get("source", "mavlink")).strip().lower()
        if source != "mavlink":
            return None

        sensor = self._selected_distance_sensor("obstacle_avoidance")
        if not sensor:
            return {
                "available": False,
                "source": "mavlink.distance_sensor",
                "sensor_id": sensor_config.get("mavlink_sensor_id"),
                "coverage_mode": sensor_config.get("coverage_mode", "forward"),
            }

        return {
            "available": True,
            "source": "mavlink.distance_sensor",
            "sensor_id": sensor.get("sensor_id"),
            "coverage_mode": sensor_config.get("coverage_mode", "forward"),
            "orientation": sensor.get("orientation"),
            "distance_meters": sensor.get("current_distance_meters"),
            "min_distance_meters": sensor.get("min_distance_meters"),
            "max_distance_meters": sensor.get("max_distance_meters"),
            "signal_quality": sensor.get("signal_quality"),
            "updated_at": sensor.get("timestamp"),
            "mavlink_sensor_id": sensor_config.get("mavlink_sensor_id"),
        }

    def _obstacle_gpio_status(self) -> dict:
        if not self._obstacle_gpio or self._obstacle_gpio_pin is None or not self._obstacle_gpio_available:
            return {
                "available": False,
                "source": "gpio",
                "gpio_pin": self._obstacle_gpio_pin,
            }

        try:
            raw = self._obstacle_gpio.input(self._obstacle_gpio_pin)
            obstacle_detected = bool(raw == self._obstacle_gpio.LOW) if self._obstacle_gpio_active_low else bool(raw == self._obstacle_gpio.HIGH)
            self._obstacle_gpio_last_update = time.time()
            return {
                "available": True,
                "source": "gpio",
                "gpio_pin": self._obstacle_gpio_pin,
                "active_low": self._obstacle_gpio_active_low,
                "raw_value": raw,
                "obstacle_detected": obstacle_detected,
                "distance_meters": None,
                "updated_at": self._obstacle_gpio_last_update,
            }
        except Exception as e:
            logger.error(f"Failed to read obstacle avoidance GPIO sensor: {str(e)}")
            return {
                "available": False,
                "source": "gpio",
                "gpio_pin": self._obstacle_gpio_pin,
                "error": str(e),
            }

    def _obstacle_ros_status(self) -> dict:
        sensor_config = self._obstacle_avoidance_sensor_config or {}
        ros_enabled = bool(sensor_config.get("ros_enabled", False))
        return {
            "available": bool(self._obstacle_ros_available or self._obstacle_ros_last_update),
            "source": "ros",
            "backend": sensor_config.get("ros_backend", "mavros"),
            "topic": sensor_config.get("ros_topic"),
            "frame_id": sensor_config.get("ros_frame_id"),
            "message_type": sensor_config.get("ros_message_type"),
            "ros_enabled": ros_enabled,
            "last_update": self._obstacle_ros_last_update,
            "distance_meters": self._obstacle_ros_last_value,
        }

    def _obstacle_avoidance_status(self) -> dict:
        sensor_config = self._obstacle_avoidance_sensor_config or {}
        source = str(sensor_config.get("source", "mavlink")).strip().lower()
        coverage_mode = str(sensor_config.get("coverage_mode", "forward")).strip().lower()

        if source == "gpio":
            status = self._obstacle_gpio_status()
        elif source == "ros":
            status = self._obstacle_ros_status()
        else:
            status = self._obstacle_mavlink_status() or {
                "available": False,
                "source": "mavlink.distance_sensor",
            }

        status.update(
            {
                "source_config": {
                    "source": source,
                    "coverage_mode": coverage_mode,
                    "mavlink_sensor_id": sensor_config.get("mavlink_sensor_id"),
                    "gpio_pin": sensor_config.get("gpio_pin"),
                    "gpio_active_low": sensor_config.get("gpio_active_low", True),
                    "ros_enabled": bool(sensor_config.get("ros_enabled", False)),
                    "ros_backend": sensor_config.get("ros_backend", "mavros"),
                    "ros_topic": sensor_config.get("ros_topic"),
                    "ros_frame_id": sensor_config.get("ros_frame_id"),
                    "ros_message_type": sensor_config.get("ros_message_type"),
                }
            }
        )
        return status

    def get_prearm_status(self) -> dict:
        """Get current pre-arm readiness and recent pre-arm failure messages."""
        if not self.vehicle:
            return {}

        try:
            with self._lock:
                prearm_messages = list(self._prearm_messages)
                last_status_text = self._last_status_text

            gps_status = self._gps_status()

            return {
                "connected": self.connected,
                "is_armable": self.vehicle.is_armable,
                "armed": self.vehicle.armed,
                "mode": self.vehicle.mode.name,
                "system_status": self.vehicle.system_status.state,
                "gps": gps_status,
                "rtk": self._rtk_status(gps_status),
                "terrain": self._terrain_status(),
                "ekf_ok": getattr(self.vehicle, "ekf_ok", None),
                "last_status_text": last_status_text,
                "prearm_messages": prearm_messages,
            }
        except Exception as e:
            logger.error(f"Error getting pre-arm status: {str(e)}")
            return {}

    def get_vehicle_state(self) -> dict:
        """Get current vehicle state"""
        if not self.vehicle:
            return {}
        
        try:
            gps_status = self._gps_status()
            return {
                'armed': self.vehicle.armed,
                'mode': self.vehicle.mode.name,
                'attitude': {
                    'roll': self.vehicle.attitude.roll,
                    'pitch': self.vehicle.attitude.pitch,
                    'yaw': self.vehicle.attitude.yaw,
                },
                'location': {
                    'latitude': self.vehicle.location.global_frame.lat,
                    'longitude': self.vehicle.location.global_frame.lon,
                    'altitude': self.vehicle.location.global_frame.alt,
                },
                'velocity': {
                    'north': self.vehicle.velocity[0],
                    'east': self.vehicle.velocity[1],
                    'down': self.vehicle.velocity[2],
                },
                'battery': {
                    'voltage': self.vehicle.battery.voltage,
                    'current': self.vehicle.battery.current,
                    'level_percent': self.vehicle.battery.level,
                },
                'ground_speed': self.vehicle.groundspeed,
                'air_speed': self.vehicle.airspeed,
                'heading': self.vehicle.heading,
                'gps': gps_status,
                'rtk': self._rtk_status(gps_status),
                'terrain': self._terrain_status(),
                'is_armable': self.vehicle.is_armable,
                'system_status': self.vehicle.system_status.state,
            }
        except Exception as e:
            logger.error(f"Error getting vehicle state: {str(e)}")
            return {}
