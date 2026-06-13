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

from dronekit import connect, Vehicle
from pymavlink.dialects.v20 import ardupilotmega as mavutil

from ..config.settings import MAVLinkConfig, ConnectionType

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages MAVLink connection to Pixhawk"""

    def __init__(self, config: MAVLinkConfig):
        self.config = config
        self.vehicle: Optional[Vehicle] = None
        self.connected = False
        self._connection_thread = None
        self._callbacks = {}
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """
        Establish connection to Pixhawk
        
        Returns:
            bool: True if connection successful
        """
        try:
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
            
            logger.info("Successfully connected to Pixhawk")
            self.connected = True
            self._trigger_callback('connected')
            
            # Start monitoring thread
            self._start_monitor_thread()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Pixhawk: {str(e)}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from Pixhawk"""
        if self.vehicle:
            self.vehicle.close()
            self.vehicle = None
        self.connected = False
        logger.info("Disconnected from Pixhawk")

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

    def _start_monitor_thread(self):
        """Start background thread to monitor connection health"""
        self._connection_thread = threading.Thread(
            target=self._monitor_connection,
            daemon=True
        )
        self._connection_thread.start()

    def _monitor_connection(self):
        """Monitor connection and detect disconnections"""
        while self.connected:
            try:
                if self.vehicle and not self.vehicle.is_armable:
                    # Basic health check
                    pass
                time.sleep(5)
            except Exception as e:
                logger.warning(f"Connection health check failed: {str(e)}")
                self.connected = False
                self._trigger_callback('disconnected')
                break

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

    def get_vehicle_state(self) -> dict:
        """Get current vehicle state"""
        if not self.vehicle:
            return {}
        
        try:
            return {
                'armed': self.vehicle.armed,
                'mode': self.vehicle.mode.name,
                'attitude': {
                    'roll': self.vehicle.attitude.roll,
                    'pitch': self.vehicle.attitude.pitch,
                    'yaw': self.vehicle.attitude.yaw,
                },
                'location': {
                    'lat': self.vehicle.location.global_frame.lat,
                    'lon': self.vehicle.location.global_frame.lon,
                    'alt': self.vehicle.location.global_frame.alt,
                },
                'velocity': {
                    'vx': self.vehicle.velocity[0],
                    'vy': self.vehicle.velocity[1],
                    'vz': self.vehicle.velocity[2],
                },
                'battery': {
                    'voltage': self.vehicle.battery.voltage,
                    'current': self.vehicle.battery.current,
                    'level': self.vehicle.battery.level,
                },
                'groundspeed': self.vehicle.groundspeed,
                'airspeed': self.vehicle.airspeed,
                'heading': self.vehicle.heading,
                'is_armable': self.vehicle.is_armable,
                'system_status': self.vehicle.system_status.state,
            }
        except Exception as e:
            logger.error(f"Error getting vehicle state: {str(e)}")
            return {}
