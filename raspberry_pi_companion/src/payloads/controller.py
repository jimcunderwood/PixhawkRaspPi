"""
Payload Controller
Manages spray pump, camera, and other auxiliary systems
"""

import logging
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Dict, Iterator, List, Optional
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

SESSION_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
SESSION_MANIFEST_FILENAME = "manifest.json"
SPRAY_SESSION_MANIFEST_FILENAME = "session.json"
SPRAY_APPLICATION_RECORD_FILENAME = "record.json"


class PayloadStatus(Enum):
    """Payload status"""
    OFF = "off"
    ON = "on"
    ERROR = "error"


class SprayPump:
    """Controls spray pump via GPIO"""

    def __init__(self, gpio_pin: int):
        self.gpio_pin = gpio_pin
        self.status = PayloadStatus.OFF
        self.total_on_time = 0.0
        self.spray_on_time = 0.0
        self._start_time = None
        self._lock = threading.Lock()

        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self.GPIO.setmode(GPIO.BCM)
            self.GPIO.setup(self.gpio_pin, GPIO.OUT)
            self.GPIO.output(self.gpio_pin, GPIO.LOW)
            logger.info(f"Spray pump initialized on GPIO pin {gpio_pin}")
        except ImportError:
            logger.warning("RPi.GPIO not available - using mock mode")
            self.GPIO = None

    def on(self) -> bool:
        """Turn spray pump on"""
        try:
            with self._lock:
                if self.GPIO:
                    self.GPIO.output(self.gpio_pin, self.GPIO.HIGH)
                self.status = PayloadStatus.ON
                self._start_time = time.time()
                logger.info("Spray pump activated")
                return True
        except Exception as e:
            logger.error(f"Failed to turn on spray pump: {str(e)}")
            self.status = PayloadStatus.ERROR
            return False

    def off(self) -> bool:
        """Turn spray pump off"""
        try:
            with self._lock:
                if self.GPIO:
                    self.GPIO.output(self.gpio_pin, self.GPIO.LOW)
                
                if self._start_time:
                    self.spray_on_time += time.time() - self._start_time
                    self._start_time = None
                
                self.status = PayloadStatus.OFF
                logger.info("Spray pump deactivated")
                return True
        except Exception as e:
            logger.error(f"Failed to turn off spray pump: {str(e)}")
            self.status = PayloadStatus.ERROR
            return False

    def get_status(self) -> Dict:
        """Get spray pump status"""
        with self._lock:
            current_session_time = 0
            if self._start_time:
                current_session_time = time.time() - self._start_time
            
            return {
                'status': self.status.value,
                'total_on_time_seconds': self.spray_on_time + current_session_time,
                'current_session_time_seconds': current_session_time,
                'gpio_pin': self.gpio_pin,
            }

    def reset_statistics(self):
        """Reset spray statistics"""
        with self._lock:
            self.spray_on_time = 0.0
            logger.info("Spray statistics reset")

    def cleanup(self):
        """Cleanup GPIO"""
        try:
            if self.GPIO:
                self.off()
                self.GPIO.cleanup(self.gpio_pin)
        except Exception as e:
            logger.error(f"Error in GPIO cleanup: {str(e)}")


class FlowSensor:
    """Flow sensor for monitoring spray flow rate"""

    def __init__(self, gpio_pin: int, pulses_per_liter: float = 450):
        self.gpio_pin = gpio_pin
        self.pulses_per_liter = pulses_per_liter
        self.pulse_count = 0
        self.total_volume = 0.0  # Liters
        self.last_flow_rate = 0.0  # L/min
        self.last_update = None
        self._lock = threading.Lock()
        self._monitoring = False
        self.GPIO = None
        self._available = False

        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self.GPIO.setmode(GPIO.BCM)
            self.GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            try:
                self.GPIO.add_event_detect(self.gpio_pin, GPIO.FALLING, callback=self._pulse_callback)
            except Exception as e:
                logger.warning(
                    "Flow sensor GPIO event detection failed for pin %s: %s. "
                    "Disabling flow sensor.",
                    self.gpio_pin,
                    str(e)
                )
                self.GPIO = None
                self._available = False
            else:
                self._available = True
                logger.info(f"Flow sensor initialized on GPIO pin {gpio_pin}")
        except ImportError:
            logger.warning("RPi.GPIO not available - using mock mode")
            self.GPIO = None
            self._available = False
        except Exception as e:
            logger.error(f"Failed to initialize flow sensor on GPIO pin {gpio_pin}: {str(e)}")
            self.GPIO = None
            self._available = False

    def _pulse_callback(self, channel):
        """Callback for pulse detection"""
        with self._lock:
            self.pulse_count += 1

    def start_monitoring(self):
        """Start flow monitoring"""
        if self.GPIO is None:
            logger.warning("Flow sensor monitoring disabled because GPIO is unavailable")
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )
        self._monitor_thread.start()
        logger.info("Flow sensor monitoring started")

    def stop_monitoring(self):
        """Stop flow monitoring"""
        self._monitoring = False
        logger.info("Flow sensor monitoring stopped")

    def _monitor_loop(self):
        """Monitor flow rate periodically"""
        while self._monitoring:
            try:
                self._calculate_flow_rate()
                time.sleep(1)
            except Exception as e:
                logger.error(f"Error in flow monitoring: {str(e)}")

    def _calculate_flow_rate(self):
        """Calculate flow rate from pulse count"""
        with self._lock:
            # Convert pulse count to volume
            volume_increment = self.pulse_count / self.pulses_per_liter
            self.total_volume += volume_increment
            
            # Flow rate in L/min (update every second)
            self.last_flow_rate = volume_increment * 60
            self.last_update = time.time()
            
            self.pulse_count = 0

    def get_status(self) -> Dict:
        """Get flow sensor status"""
        with self._lock:
            return {
                'total_volume_liters': self.total_volume,
                'flow_rate_liters_per_minute': self.last_flow_rate,
                'gpio_pin': self.gpio_pin,
                'pulses_per_liter': self.pulses_per_liter,
                'available': self._available,
                'updated_at': self.last_update,
            }

    def reset(self):
        """Reset flow meter"""
        with self._lock:
            self.pulse_count = 0
            self.total_volume = 0.0
            self.last_flow_rate = 0.0
            logger.info("Flow sensor reset")

    def cleanup(self):
        """Cleanup GPIO"""
        try:
            self.stop_monitoring()
            if self.GPIO:
                self.GPIO.cleanup(self.gpio_pin)
        except Exception as e:
            logger.error(f"Error in flow sensor cleanup: {str(e)}")

    def is_available(self) -> bool:
        """Return whether the flow sensor is ready for use."""
        return self._available


class CameraTrigger:
    """Optional GPIO trigger output for external camera shutters."""

    def __init__(self, gpio_pin: int, pulse_ms: int = 100):
        self.gpio_pin = gpio_pin
        self.pulse_ms = pulse_ms
        self.trigger_count = 0
        self.last_triggered_at = None
        self.GPIO = None
        self._available = False
        self._lock = threading.Lock()

        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self.GPIO.setmode(GPIO.BCM)
            self.GPIO.setup(self.gpio_pin, GPIO.OUT)
            self.GPIO.output(self.gpio_pin, GPIO.LOW)
            self._available = True
            logger.info(f"Camera trigger initialized on GPIO pin {gpio_pin}")
        except ImportError:
            logger.warning("RPi.GPIO not available - camera trigger disabled")
        except Exception as e:
            logger.error(f"Failed to initialize camera trigger on GPIO pin {gpio_pin}: {str(e)}")

    def trigger(self) -> Optional[Dict]:
        """Pulse the trigger line and return trigger metadata."""
        now = time.time()
        try:
            with self._lock:
                if self.GPIO:
                    self.GPIO.output(self.gpio_pin, self.GPIO.HIGH)
                    time.sleep(max(1, self.pulse_ms) / 1000)
                    self.GPIO.output(self.gpio_pin, self.GPIO.LOW)
                self.trigger_count += 1
                self.last_triggered_at = now
                return {
                    "triggered_at": now,
                    "trigger_count": self.trigger_count,
                    "gpio_pin": self.gpio_pin,
                    "pulse_ms": self.pulse_ms,
                    "available": self._available,
                }
        except Exception as e:
            logger.error(f"Camera trigger failed: {str(e)}")
            return None

    def get_status(self) -> Dict:
        return {
            "available": self._available,
            "gpio_pin": self.gpio_pin,
            "pulse_ms": self.pulse_ms,
            "trigger_count": self.trigger_count,
            "last_triggered_at": self.last_triggered_at,
        }

    def cleanup(self):
        try:
            if self.GPIO:
                self.GPIO.cleanup(self.gpio_pin)
        except Exception as e:
            logger.error(f"Error in camera trigger cleanup: {str(e)}")

    def is_available(self) -> bool:
        return self._available


class MCP3008ADC:
    """Minimal MCP3008 ADC reader over SPI."""

    def __init__(self, bus: int = 0, device: int = 0, max_voltage: float = 3.3):
        self.bus = bus
        self.device = device
        self.max_voltage = max_voltage
        self.spi = None
        self._available = False

        try:
            import spidev
            self.spi = spidev.SpiDev()
            self.spi.open(bus, device)
            self.spi.max_speed_hz = 1350000
            self._available = True
        except ImportError:
            logger.warning("spidev not available - ADC sensors disabled")
        except Exception as e:
            logger.error(f"Failed to initialize MCP3008 ADC on SPI {bus}.{device}: {str(e)}")

    def read_voltage(self, channel: int) -> Optional[float]:
        if not self.spi or not 0 <= channel <= 7:
            return None

        try:
            response = self.spi.xfer2([1, (8 + channel) << 4, 0])
            raw = ((response[1] & 3) << 8) + response[2]
            return (raw / 1023.0) * self.max_voltage
        except Exception as e:
            logger.error(f"Failed to read ADC channel {channel}: {str(e)}")
            return None

    def cleanup(self):
        try:
            if self.spi:
                self.spi.close()
        except Exception as e:
            logger.error(f"Error closing ADC: {str(e)}")

    def is_available(self) -> bool:
        return self._available


class ScaledSensor:
    """GPIO threshold or ADC-backed scaled sensor."""

    def __init__(
        self,
        name: str,
        source: str,
        gpio_pin: Optional[int] = None,
        adc: Optional[MCP3008ADC] = None,
        adc_channel: int = 0,
        min_voltage: float = 0.5,
        max_voltage: float = 4.5,
        min_value: float = 0.0,
        max_value: float = 100.0,
        unit: str = "",
    ):
        self.name = name
        self.source = source
        self.gpio_pin = gpio_pin
        self.adc = adc
        self.adc_channel = adc_channel
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.min_value = min_value
        self.max_value = max_value
        self.unit = unit
        self.GPIO = None
        self._available = False

        if self.source == "gpio":
            self._init_gpio()
        elif self.source == "adc":
            self._available = bool(self.adc and self.adc.is_available())
        else:
            logger.warning("%s sensor source '%s' is unsupported", self.name, self.source)

    def _init_gpio(self):
        if self.gpio_pin is None:
            logger.warning("%s sensor GPIO source selected but no pin configured", self.name)
            return

        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self.GPIO.setmode(GPIO.BCM)
            self.GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._available = True
            logger.info(f"{self.name} sensor initialized on GPIO pin {self.gpio_pin}")
        except ImportError:
            logger.warning("RPi.GPIO not available - %s sensor disabled", self.name)
        except Exception as e:
            logger.error(f"Failed to initialize {self.name} sensor on GPIO pin {self.gpio_pin}: {str(e)}")

    def _scale_voltage(self, voltage: float) -> float:
        if self.max_voltage <= self.min_voltage:
            return self.min_value
        ratio = (voltage - self.min_voltage) / (self.max_voltage - self.min_voltage)
        ratio = max(0.0, min(1.0, ratio))
        return self.min_value + ratio * (self.max_value - self.min_value)

    def get_status(self) -> Dict:
        status = {
            "name": self.name,
            "available": self._available,
            "source": self.source,
            "gpio_pin": self.gpio_pin,
            "adc_channel": self.adc_channel if self.source == "adc" else None,
            "unit": self.unit,
            "value": None,
            "voltage": None,
            "is_active": None,
            "updated_at": None,
        }

        if not self._available:
            return status

        if self.source == "gpio" and self.GPIO and self.gpio_pin is not None:
            raw = self.GPIO.input(self.gpio_pin)
            status["is_active"] = bool(raw == self.GPIO.LOW)
            status["value"] = 1 if status["is_active"] else 0
            status["updated_at"] = time.time()
            return status

        if self.source == "adc" and self.adc:
            voltage = self.adc.read_voltage(self.adc_channel)
            status["voltage"] = voltage
            status["value"] = self._scale_voltage(voltage) if voltage is not None else None
            status["updated_at"] = time.time() if voltage is not None else None
            return status

        return status

    def cleanup(self):
        try:
            if self.GPIO and self.gpio_pin is not None:
                self.GPIO.cleanup(self.gpio_pin)
        except Exception as e:
            logger.error(f"Error in {self.name} sensor cleanup: {str(e)}")

    def is_available(self) -> bool:
        return self._available


class SpraySessionStore:
    """File-backed spray session metadata."""

    def __init__(self, session_directory: str):
        self.session_directory = Path(session_directory)
        self._lock = threading.Lock()
        try:
            self.session_directory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create spray session directory {self.session_directory}: {str(e)}")

    def _safe_session_name(self, session: Optional[str]) -> str:
        if not session:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            return f"spray_{timestamp}"

        safe_name = SESSION_NAME_PATTERN.sub("_", session.strip())
        safe_name = safe_name.strip("._-")
        return safe_name[:80] or "default"

    def _session_directory(self, session: str) -> Path:
        return self.session_directory / self._safe_session_name(session)

    def _manifest_path(self, session: str) -> Path:
        return self._session_directory(session) / SPRAY_SESSION_MANIFEST_FILENAME

    def start_session(
        self,
        session: Optional[str],
        telemetry_snapshot: Optional[Dict] = None,
    ) -> Dict:
        safe_session = self._safe_session_name(session)
        now = time.time()
        manifest = {
            "session": safe_session,
            "status": "active",
            "started_at": now,
            "stopped_at": None,
            "duration_seconds": 0,
            "start_telemetry": telemetry_snapshot,
            "stop_telemetry": None,
            "start_flow": None,
            "stop_flow": None,
            "total_volume_liters": None,
        }
        self._write_manifest(safe_session, manifest)
        return manifest

    def stop_session(
        self,
        session: str,
        telemetry_snapshot: Optional[Dict] = None,
        flow_status: Optional[Dict] = None,
    ) -> Dict:
        manifest = self.get_session(session) or {
            "session": self._safe_session_name(session),
            "started_at": None,
            "start_flow": None,
        }
        now = time.time()
        started_at = manifest.get("started_at") or now
        start_flow = manifest.get("start_flow") or {}
        start_volume = start_flow.get("total_volume_liters")
        stop_volume = (flow_status or {}).get("total_volume_liters")
        total_volume = None
        if start_volume is not None and stop_volume is not None:
            total_volume = max(0, stop_volume - start_volume)

        manifest.update(
            {
                "status": "stopped",
                "stopped_at": now,
                "duration_seconds": max(0, now - started_at),
                "stop_telemetry": telemetry_snapshot,
                "stop_flow": flow_status,
                "total_volume_liters": total_volume,
            }
        )
        self._write_manifest(manifest["session"], manifest)
        return manifest

    def attach_start_flow(self, session: str, flow_status: Optional[Dict]):
        manifest = self.get_session(session)
        if not manifest:
            return
        manifest["start_flow"] = flow_status
        self._write_manifest(session, manifest)

    def get_session(self, session: str) -> Optional[Dict]:
        manifest_path = self._manifest_path(session)
        if not manifest_path.is_file():
            return None
        try:
            with manifest_path.open("r", encoding="utf-8") as manifest_file:
                return json.load(manifest_file)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load spray session manifest {manifest_path}: {str(e)}")
            return None

    def list_sessions(self) -> List[Dict]:
        sessions = []
        if not self.session_directory.is_dir():
            return sessions
        for manifest_path in self.session_directory.glob(f"*/{SPRAY_SESSION_MANIFEST_FILENAME}"):
            try:
                with manifest_path.open("r", encoding="utf-8") as manifest_file:
                    sessions.append(json.load(manifest_file))
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"Failed to load spray session manifest {manifest_path}: {str(e)}")
        sessions.sort(
            key=lambda item: item.get("stopped_at") or item.get("started_at") or 0,
            reverse=True,
        )
        return sessions

    def _write_manifest(self, session: str, manifest: Dict):
        manifest_path = self._manifest_path(session)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = manifest_path.with_suffix(".json.tmp")
        with self._lock:
            try:
                with tmp_path.open("w", encoding="utf-8") as manifest_file:
                    json.dump(manifest, manifest_file, indent=2, sort_keys=True)
                    manifest_file.write("\n")
                tmp_path.replace(manifest_path)
            except OSError as e:
                logger.error(f"Failed to write spray session manifest {manifest_path}: {str(e)}")


class SprayApplicationRecordStore:
    """File-backed spray application records."""

    def __init__(self, record_directory: str):
        self.record_directory = Path(record_directory)
        self._lock = threading.Lock()
        try:
            self.record_directory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create application record directory {self.record_directory}: {str(e)}")

    def _safe_name(self, name: str) -> str:
        safe_name = SESSION_NAME_PATTERN.sub("_", name.strip())
        safe_name = safe_name.strip("._-")
        return safe_name[:80] or "record"

    def _record_path(self, session: str) -> Path:
        return self.record_directory / self._safe_name(session) / SPRAY_APPLICATION_RECORD_FILENAME

    def create_record(
        self,
        session_manifest: Dict,
        payload_status: Dict,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        session = session_manifest["session"]
        now = time.time()
        record = {
            "session": session,
            "created_at": now,
            "updated_at": now,
            "status": session_manifest.get("status"),
            "started_at": session_manifest.get("started_at"),
            "stopped_at": session_manifest.get("stopped_at"),
            "duration_seconds": session_manifest.get("duration_seconds"),
            "total_volume_liters": session_manifest.get("total_volume_liters"),
            "start_telemetry": session_manifest.get("start_telemetry"),
            "stop_telemetry": session_manifest.get("stop_telemetry"),
            "start_flow": session_manifest.get("start_flow"),
            "stop_flow": session_manifest.get("stop_flow"),
            "payload_status": payload_status,
            "metadata": metadata or {},
        }
        self._write_record(session, record)
        return record

    def get_record(self, session: str) -> Optional[Dict]:
        path = self._record_path(session)
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as record_file:
                return json.load(record_file)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to read application record {path}: {str(e)}")
            return None

    def list_records(self) -> List[Dict]:
        records = []
        for record_path in self.record_directory.glob(f"*/{SPRAY_APPLICATION_RECORD_FILENAME}"):
            try:
                with record_path.open("r", encoding="utf-8") as record_file:
                    records.append(json.load(record_file))
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"Failed to read application record {record_path}: {str(e)}")
        records.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or 0, reverse=True)
        return records

    def _write_record(self, session: str, record: Dict):
        path = self._record_path(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        with self._lock:
            try:
                with tmp_path.open("w", encoding="utf-8") as record_file:
                    json.dump(record, record_file, indent=2, sort_keys=True)
                    record_file.write("\n")
                tmp_path.replace(path)
            except OSError as e:
                logger.error(f"Failed to write application record {path}: {str(e)}")


class CameraController:
    """Controls camera system"""

    def __init__(
        self,
        camera_id: int = 0,
        photo_directory: str = "/tmp/drone_photos",
        camera_trigger: Optional[CameraTrigger] = None,
    ):
        self.camera_id = camera_id
        self.photo_directory = Path(photo_directory)
        self.camera_trigger = camera_trigger
        self.is_recording = False
        self.total_photos = 0
        self.total_video_time = 0.0
        self._camera = None
        self._video_writer = None
        self._record_start = None
        self._capture_running = False
        self._capture_thread = None
        self._latest_frame = None
        self._last_frame_time = None
        self._lock = threading.Lock()

        try:
            self.photo_directory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create photo directory {self.photo_directory}: {str(e)}")

        try:
            import cv2
            self.cv2 = cv2
            self._camera = cv2.VideoCapture(camera_id)
            if not self._camera.isOpened():
                logger.warning(f"Camera {camera_id} not found")
            else:
                logger.info(f"Camera {camera_id} initialized")
                self._start_capture_loop()
        except ImportError:
            logger.warning("OpenCV not available - camera disabled")

    def _start_capture_loop(self):
        self._capture_running = True
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
        )
        self._capture_thread.start()

    def _capture_loop(self):
        while self._capture_running:
            try:
                if not self._camera or not self._camera.isOpened():
                    time.sleep(0.25)
                    continue

                ret, frame = self._camera.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                with self._lock:
                    self._latest_frame = frame
                    self._last_frame_time = time.time()
                    if self.is_recording and self._video_writer:
                        self._video_writer.write(frame)

            except Exception as e:
                logger.error(f"Camera capture loop failed: {str(e)}")
                time.sleep(0.25)

    def _get_latest_frame(self):
        with self._lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()

        if self._camera and self._camera.isOpened():
            ret, frame = self._camera.read()
            if ret:
                with self._lock:
                    self._latest_frame = frame
                    self._last_frame_time = time.time()
                return frame.copy()

        return None

    def _safe_session_name(self, session: Optional[str]) -> str:
        if not session:
            return "default"

        safe_name = SESSION_NAME_PATTERN.sub("_", session.strip())
        safe_name = safe_name.strip("._-")
        return safe_name[:80] or "default"

    def sanitize_session(self, session: Optional[str]) -> str:
        """Return the filesystem-safe session name."""
        return self._safe_session_name(session)

    def _session_directory(self, session: Optional[str]) -> Path:
        return self.photo_directory / self._safe_session_name(session)

    def _manifest_path(self, session: Optional[str]) -> Path:
        return self._session_directory(session) / SESSION_MANIFEST_FILENAME

    def _load_session_manifest(self, session: Optional[str]) -> Dict:
        safe_session = self._safe_session_name(session)
        manifest_path = self._manifest_path(safe_session)
        if not manifest_path.is_file():
            return {"session": safe_session, "photos": []}

        try:
            with manifest_path.open("r", encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load photo manifest {manifest_path}: {str(e)}")
            return {"session": safe_session, "photos": []}

        photos = manifest.get("photos", [])
        if not isinstance(photos, list):
            photos = []

        return {
            "session": safe_session,
            "photos": photos,
            "updated_at": manifest.get("updated_at"),
        }

    def _write_session_manifest(self, session: Optional[str], manifest: Dict):
        manifest_path = self._manifest_path(session)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = manifest_path.with_suffix(".json.tmp")

        try:
            with tmp_path.open("w", encoding="utf-8") as manifest_file:
                json.dump(manifest, manifest_file, indent=2, sort_keys=True)
                manifest_file.write("\n")
            tmp_path.replace(manifest_path)
        except OSError as e:
            logger.error(f"Failed to write photo manifest {manifest_path}: {str(e)}")

    def _photo_metadata(self, photo_path: Path, session: str, captured_at: Optional[float] = None) -> Dict:
        stat = photo_path.stat()
        captured_at = captured_at if captured_at is not None else stat.st_mtime
        return {
            "filename": photo_path.name,
            "path": str(photo_path),
            "session": session,
            "size_bytes": stat.st_size,
            "captured_at": captured_at,
            "camera_id": self.camera_id,
        }

    def _record_photo_in_manifest(self, photo_path: Path, session: str, captured_at: float) -> Dict:
        manifest = self._load_session_manifest(session)
        photo = self._photo_metadata(photo_path, session, captured_at)

        photos = [
            existing
            for existing in manifest.get("photos", [])
            if existing.get("filename") != photo["filename"]
        ]
        photos.append(photo)
        photos.sort(key=lambda item: item.get("captured_at", 0), reverse=True)

        manifest["session"] = session
        manifest["photos"] = photos
        manifest["updated_at"] = time.time()
        self._write_session_manifest(session, manifest)

        return photo

    def _default_photo_filename(self, session: Optional[str] = None) -> Path:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        monotonic_ms = int(time.monotonic() * 1000) % 100000
        return self._session_directory(session) / f"photo_{timestamp}_{monotonic_ms:05d}.jpg"

    def capture_photo(
        self,
        filename: Optional[str] = None,
        session: Optional[str] = None,
        telemetry_snapshot: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Capture single photo"""
        try:
            trigger_event = self.camera_trigger.trigger() if self.camera_trigger else None
            if not self._camera or not self._camera.isOpened():
                logger.error("Camera not available")
                return None

            safe_session = self._safe_session_name(session)
            photo_path = Path(filename) if filename else self._default_photo_filename(safe_session)
            photo_path.parent.mkdir(parents=True, exist_ok=True)
            
            frame = self._get_latest_frame()
            if frame is None:
                logger.error("Failed to capture frame")
                return None

            if not self.cv2.imwrite(str(photo_path), frame):
                logger.error(f"Failed to write photo: {photo_path}")
                return None
            captured_at = time.time()
            with self._lock:
                self.total_photos += 1
            photo = self._record_photo_in_manifest(photo_path, safe_session, captured_at)
            photo["telemetry"] = telemetry_snapshot
            photo["geotag"] = self._geotag_from_telemetry(telemetry_snapshot)
            photo["camera_trigger"] = trigger_event
            manifest = self._load_session_manifest(safe_session)
            for manifest_photo in manifest.get("photos", []):
                if manifest_photo.get("filename") == photo["filename"]:
                    manifest_photo["telemetry"] = telemetry_snapshot
                    manifest_photo["geotag"] = photo["geotag"]
                    manifest_photo["camera_trigger"] = trigger_event
            manifest["updated_at"] = time.time()
            self._write_session_manifest(safe_session, manifest)
            logger.info(f"Photo captured: {photo_path}")
            return photo
                
        except Exception as e:
            logger.error(f"Photo capture failed: {str(e)}")
            return None

    def _geotag_from_telemetry(self, telemetry_snapshot: Optional[Dict]) -> Optional[Dict]:
        if not telemetry_snapshot:
            return None

        location = telemetry_snapshot.get("location") or {}
        if location.get("latitude") is None or location.get("longitude") is None:
            return None

        return {
            "location": {
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "altitude": location.get("altitude"),
            },
            "heading": telemetry_snapshot.get("heading"),
            "gps": telemetry_snapshot.get("gps"),
            "rtk": telemetry_snapshot.get("rtk"),
            "terrain": telemetry_snapshot.get("terrain"),
            "captured_at": telemetry_snapshot.get("timestamp"),
        }

    def get_recent_photos(self, limit: int = 10, session: Optional[str] = None) -> list:
        """Return recent captured photo metadata newest first."""
        if session:
            manifest = self._load_session_manifest(session)
            photos = [
                photo
                for photo in manifest.get("photos", [])
                if self.get_photo_path(photo.get("filename", ""), session=manifest["session"])
            ]
            if not photos:
                session_dir = self._session_directory(session)
                for path in session_dir.glob("*.jpg"):
                    if not path.is_file():
                        continue
                    try:
                        photos.append(
                            self._photo_metadata(path, manifest["session"], path.stat().st_mtime)
                        )
                    except OSError:
                        continue
            photos.sort(key=lambda item: item.get("captured_at", 0), reverse=True)
            return photos[:limit]

        try:
            search_dir = self.photo_directory
            photos = sorted(
                (
                    path
                    for path in search_dir.glob("**/*.jpg")
                    if path.is_file()
                ),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError as e:
            logger.error(f"Failed to list photos in {self.photo_directory}: {str(e)}")
            return []

        recent = []
        for path in photos[:limit]:
            try:
                stat = path.stat()
            except OSError:
                continue

            recent.append(
                self._photo_metadata(path, self._photo_session(path), stat.st_mtime)
            )

        return recent

    def _photo_session(self, photo_path: Path) -> str:
        try:
            relative_path = photo_path.relative_to(self.photo_directory)
        except ValueError:
            return "default"

        if len(relative_path.parts) > 1:
            return relative_path.parts[0]

        return "default"

    def get_photo_path(self, filename: str, session: Optional[str] = None) -> Optional[Path]:
        """Return a safe path for a captured photo filename."""
        photo_path = (self._session_directory(session) / os.path.basename(filename)).resolve()
        photo_dir = self.photo_directory.resolve()

        try:
            photo_path.relative_to(photo_dir)
        except ValueError:
            return None

        if not photo_path.is_file() or photo_path.suffix.lower() != ".jpg":
            return None

        return photo_path

    def reset_photos(self, session: Optional[str] = None) -> int:
        """Delete captured photos and return the number removed."""
        target_dir = self._session_directory(session) if session else self.photo_directory
        if not target_dir.exists():
            return 0

        removed = len([path for path in target_dir.glob("**/*.jpg") if path.is_file()])
        try:
            shutil.rmtree(target_dir)
        except OSError as e:
            logger.error(f"Failed to reset photo directory {target_dir}: {str(e)}")

        if not session:
            self.photo_directory.mkdir(parents=True, exist_ok=True)

        return removed

    def get_session_manifest(self, session: str) -> Optional[Dict]:
        """Return the manifest for a photo session."""
        session_dir = self._session_directory(session)
        if not session_dir.is_dir():
            return None

        manifest = self._load_session_manifest(session)
        photos = [
            photo
            for photo in manifest.get("photos", [])
            if self.get_photo_path(photo.get("filename", ""), session=manifest["session"])
        ]

        if not photos:
            photos = self.get_recent_photos(500, session=session)

        photos.sort(key=lambda item: item.get("captured_at", 0), reverse=True)
        manifest["photos"] = photos
        manifest["photo_count"] = len(photos)
        manifest["latest_photo"] = photos[0] if photos else None
        return manifest

    def list_photo_sessions(self) -> list:
        """Return available photo sessions with summary metadata."""
        sessions = []
        if not self.photo_directory.is_dir():
            return sessions

        for session_dir in self.photo_directory.iterdir():
            if not session_dir.is_dir():
                continue

            manifest = self.get_session_manifest(session_dir.name)
            if not manifest:
                continue

            sessions.append(
                {
                    "session": manifest["session"],
                    "photo_count": manifest.get("photo_count", 0),
                    "updated_at": manifest.get("updated_at"),
                    "latest_photo": manifest.get("latest_photo"),
                }
            )

        sessions.sort(
            key=lambda item: (
                item.get("updated_at")
                or (item.get("latest_photo") or {}).get("captured_at")
                or 0
            ),
            reverse=True,
        )
        return sessions

    def get_session_archive_path(self, session: str, archive_path: Path) -> Optional[Path]:
        """Create a zip archive for a photo session folder."""
        session_dir = self._session_directory(session)
        if not session_dir.is_dir():
            return None

        photos = [path for path in session_dir.glob("*.jpg") if path.is_file()]
        if not photos:
            return None

        import zipfile

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for photo_path in photos:
                archive.write(photo_path, arcname=photo_path.name)
            manifest_path = self._manifest_path(session)
            if manifest_path.is_file():
                archive.write(manifest_path, arcname=SESSION_MANIFEST_FILENAME)

        return archive_path

    def start_video_recording(self, filename: str) -> bool:
        """Start video recording"""
        try:
            if not self._camera or not self._camera.isOpened():
                logger.error("Camera not available")
                return False
            
            with self._lock:
                fourcc = self.cv2.VideoWriter_fourcc(*'mp4v')
                fps = int(self._camera.get(self.cv2.CAP_PROP_FPS))
                if fps <= 0:
                    fps = 10
                width = int(self._camera.get(self.cv2.CAP_PROP_FRAME_WIDTH))
                height = int(self._camera.get(self.cv2.CAP_PROP_FRAME_HEIGHT))
                if (width <= 0 or height <= 0) and self._latest_frame is not None:
                    height, width = self._latest_frame.shape[:2]
                if width <= 0 or height <= 0:
                    logger.error("Unable to determine camera frame size for recording")
                    return False
                
                self._video_writer = self.cv2.VideoWriter(
                    filename, fourcc, fps, (width, height)
                )
                self.is_recording = True
                self._record_start = time.time()
            
            logger.info(f"Video recording started: {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Video recording start failed: {str(e)}")
            return False

    def generate_mjpeg_frames(
        self,
        fps: int = 10,
        jpeg_quality: int = 80,
    ) -> Iterator[bytes]:
        """Yield camera frames as multipart MJPEG chunks."""
        if not self._camera or not self._camera.isOpened():
            logger.error("Camera not available")
            return

        frame_delay = 1.0 / max(1, fps)
        encode_params = [
            int(self.cv2.IMWRITE_JPEG_QUALITY),
            max(1, min(100, jpeg_quality)),
        ]

        while True:
            try:
                frame = self._get_latest_frame()
                if frame is None:
                    logger.warning("Failed to read camera frame for MJPEG stream")
                    time.sleep(frame_delay)
                    continue

                success, encoded = self.cv2.imencode(".jpg", frame, encode_params)
                if not success:
                    logger.warning("Failed to encode camera frame for MJPEG stream")
                    time.sleep(frame_delay)
                    continue

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + encoded.tobytes()
                    + b"\r\n"
                )
                time.sleep(frame_delay)

            except GeneratorExit:
                break
            except Exception as e:
                logger.error(f"Camera stream failed: {str(e)}")
                break

    def stop_video_recording(self) -> bool:
        """Stop video recording"""
        try:
            with self._lock:
                if self._video_writer:
                    self._video_writer.release()
                    self._video_writer = None

                if self._record_start:
                    self.total_video_time += time.time() - self._record_start
                    self._record_start = None
                
                self.is_recording = False
            
            logger.info("Video recording stopped")
            return True
            
        except Exception as e:
            logger.error(f"Video recording stop failed: {str(e)}")
            return False

    def get_status(self) -> Dict:
        """Get camera status"""
        with self._lock:
            current_record_time = 0
            if self._record_start:
                current_record_time = time.time() - self._record_start
            
            return {
                'camera_id': self.camera_id,
                'available': bool(self._camera and self._camera.isOpened()),
                'is_recording': self.is_recording,
                'total_photos': self.total_photos,
                'total_video_time_seconds': self.total_video_time + current_record_time,
                'current_recording_time_seconds': current_record_time,
                'trigger': self.camera_trigger.get_status() if self.camera_trigger else None,
            }

    def is_available(self) -> bool:
        return bool(self._camera and self._camera.isOpened())

    def cleanup(self):
        """Release camera"""
        try:
            if self.is_recording:
                self.stop_video_recording()
            self._capture_running = False
            if self._capture_thread and self._capture_thread.is_alive():
                self._capture_thread.join(timeout=2)
            if self._camera:
                self._camera.release()
            if self.camera_trigger:
                self.camera_trigger.cleanup()
            logger.info("Camera released")
        except Exception as e:
            logger.error(f"Error in camera cleanup: {str(e)}")


class PayloadController:
    """Master payload controller"""

    def __init__(self, config):
        self.spray_pump = SprayPump(config.spray_pump_pin)
        self.flow_sensor = None
        self.pressure_sensor = None
        self.tank_level_sensor = None
        self.adc = None
        self.camera_trigger = None
        self.spray_sessions = SpraySessionStore(config.spray_session_directory)
        self.application_records = SprayApplicationRecordStore(
            config.spray_application_record_directory
        )
        self.active_spray_session = None
        self.tank_capacity_liters = config.tank_capacity_liters
        self.tank_min_level_percent = config.tank_min_level_percent

        if config.flow_sensor_enabled:
            flow_sensor = FlowSensor(
                config.flow_sensor_pin,
                pulses_per_liter=config.flow_sensor_pulses_per_liter,
            )
            if flow_sensor.is_available():
                self.flow_sensor = flow_sensor
            else:
                logger.warning(
                    "Flow sensor on GPIO pin %s is unavailable and has been disabled.",
                    config.flow_sensor_pin,
                )

        needs_adc = (
            config.pressure_sensor_enabled and config.pressure_sensor_source == "adc"
        ) or (
            config.tank_level_sensor_enabled and config.tank_level_sensor_source == "adc"
        )
        if needs_adc:
            self.adc = MCP3008ADC()

        if config.pressure_sensor_enabled:
            pressure_sensor = ScaledSensor(
                name="pressure",
                source=config.pressure_sensor_source,
                gpio_pin=config.pressure_sensor_pin,
                adc=self.adc,
                adc_channel=config.pressure_sensor_adc_channel,
                min_voltage=config.pressure_sensor_min_voltage,
                max_voltage=config.pressure_sensor_max_voltage,
                min_value=config.pressure_sensor_min_psi,
                max_value=config.pressure_sensor_max_psi,
                unit="psi",
            )
            if pressure_sensor.is_available():
                self.pressure_sensor = pressure_sensor
            else:
                logger.warning("Pressure sensor is configured but unavailable.")

        if config.tank_level_sensor_enabled:
            tank_level_sensor = ScaledSensor(
                name="tank_level",
                source=config.tank_level_sensor_source,
                gpio_pin=config.tank_level_sensor_pin,
                adc=self.adc,
                adc_channel=config.tank_level_sensor_adc_channel,
                min_voltage=config.tank_level_sensor_min_voltage,
                max_voltage=config.tank_level_sensor_max_voltage,
                min_value=0,
                max_value=100,
                unit="percent",
            )
            if tank_level_sensor.is_available():
                self.tank_level_sensor = tank_level_sensor
            else:
                logger.warning("Tank level sensor is configured but unavailable.")

        if config.camera_trigger_enabled:
            camera_trigger = CameraTrigger(
                config.camera_trigger_pin,
                pulse_ms=config.camera_trigger_pulse_ms,
            )
            if camera_trigger.is_available():
                self.camera_trigger = camera_trigger
            else:
                logger.warning(
                    "Camera trigger on GPIO pin %s is unavailable and has been disabled.",
                    config.camera_trigger_pin,
                )

        self.camera = (
            CameraController(
                config.camera_port,
                config.photo_directory,
                camera_trigger=self.camera_trigger,
            )
            if config.camera_enabled
            else None
        )

    def arm_spray(
        self,
        session: Optional[str] = None,
        telemetry_snapshot: Optional[Dict] = None,
    ) -> bool:
        """Activate spray system"""
        if self.spray_pump.on():
            spray_session = self.spray_sessions.start_session(session, telemetry_snapshot)
            self.active_spray_session = spray_session["session"]
            if self.flow_sensor:
                self.flow_sensor.start_monitoring()
                self.spray_sessions.attach_start_flow(
                    self.active_spray_session,
                    self.flow_sensor.get_status(),
                )
            return True
        return False

    def disarm_spray(self, telemetry_snapshot: Optional[Dict] = None) -> bool:
        """Deactivate spray system"""
        if self.flow_sensor:
            self.flow_sensor.stop_monitoring()
        stopped = self.spray_pump.off()
        if stopped and self.active_spray_session:
            flow_status = self.flow_sensor.get_status() if self.flow_sensor else None
            self.spray_sessions.stop_session(
                self.active_spray_session,
                telemetry_snapshot=telemetry_snapshot,
                flow_status=flow_status,
            )
            self.active_spray_session = None
        return stopped

    def get_payload_status(self) -> Dict:
        """Get all payload status"""
        status = {
            'spray_pump': self.spray_pump.get_status(),
            'active_spray_session': self.active_spray_session,
        }
        
        if self.flow_sensor:
            status['flow_sensor'] = self.flow_sensor.get_status()

        if self.pressure_sensor:
            status['pressure_sensor'] = self.pressure_sensor.get_status()

        if self.tank_level_sensor:
            tank_status = self.tank_level_sensor.get_status()
            if tank_status.get("value") is not None and tank_status.get("unit") == "percent":
                tank_status["volume_liters"] = (
                    max(0, min(100, tank_status["value"])) / 100
                ) * self.tank_capacity_liters
                tank_status["capacity_liters"] = self.tank_capacity_liters
                tank_status["minimum_level_percent"] = self.tank_min_level_percent
                tank_status["is_below_minimum"] = tank_status["value"] < self.tank_min_level_percent
            status['tank_level_sensor'] = tank_status

        if self.camera_trigger and not self.camera:
            status['camera_trigger'] = self.camera_trigger.get_status()
        
        if self.camera:
            status['camera'] = self.camera.get_status()
        
        return status

    def list_spray_sessions(self) -> List[Dict]:
        return self.spray_sessions.list_sessions()

    def get_spray_session(self, session: str) -> Optional[Dict]:
        return self.spray_sessions.get_session(session)

    def create_application_record(
        self,
        session: str,
        metadata: Optional[Dict] = None,
    ) -> Optional[Dict]:
        spray_session = self.get_spray_session(session)
        if not spray_session:
            return None
        return self.application_records.create_record(
            spray_session,
            self.get_payload_status(),
            metadata=metadata,
        )

    def get_application_record(self, session: str) -> Optional[Dict]:
        return self.application_records.get_record(session)

    def list_application_records(self) -> List[Dict]:
        return self.application_records.list_records()

    def cleanup(self):
        """Cleanup all payloads"""
        self.disarm_spray()
        self.spray_pump.cleanup()
        
        if self.flow_sensor:
            self.flow_sensor.cleanup()

        if self.pressure_sensor:
            self.pressure_sensor.cleanup()

        if self.tank_level_sensor:
            self.tank_level_sensor.cleanup()

        if self.adc:
            self.adc.cleanup()
        
        if self.camera:
            self.camera.cleanup()
        elif self.camera_trigger:
            self.camera_trigger.cleanup()
