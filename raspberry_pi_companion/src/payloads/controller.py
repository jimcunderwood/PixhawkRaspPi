"""
Payload Controller
Manages spray pump, camera, and other auxiliary systems
"""

import logging
import threading
import time
from typing import Optional, Dict
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


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
                'total_on_time': self.spray_on_time + current_session_time,
                'current_session_time': current_session_time,
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

    def __init__(self, gpio_pin: int):
        self.gpio_pin = gpio_pin
        self.pulse_count = 0
        self.total_volume = 0.0  # Liters
        self.last_flow_rate = 0.0  # L/min
        self._lock = threading.Lock()
        self._monitoring = False

        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self.GPIO.setmode(GPIO.BCM)
            self.GPIO.setup(self.gpio_pin, GPIO.IN)
            self.GPIO.add_event_detect(self.gpio_pin, GPIO.FALLING, callback=self._pulse_callback)
            logger.info(f"Flow sensor initialized on GPIO pin {gpio_pin}")
        except ImportError:
            logger.warning("RPi.GPIO not available - using mock mode")
            self.GPIO = None

    def _pulse_callback(self, channel):
        """Callback for pulse detection"""
        with self._lock:
            self.pulse_count += 1

    def start_monitoring(self):
        """Start flow monitoring"""
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
            # Typical sensor: 450 pulses per liter
            pulses_per_liter = 450
            
            # Convert pulse count to volume
            volume_increment = self.pulse_count / pulses_per_liter
            self.total_volume += volume_increment
            
            # Flow rate in L/min (update every second)
            self.last_flow_rate = volume_increment * 60
            
            self.pulse_count = 0

    def get_status(self) -> Dict:
        """Get flow sensor status"""
        with self._lock:
            return {
                'total_volume': self.total_volume,
                'flow_rate': self.last_flow_rate,
                'gpio_pin': self.gpio_pin,
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


class CameraController:
    """Controls camera system"""

    def __init__(self, camera_id: int = 0):
        self.camera_id = camera_id
        self.is_recording = False
        self.total_photos = 0
        self.total_video_time = 0.0
        self._camera = None
        self._record_start = None
        self._lock = threading.Lock()

        try:
            import cv2
            self.cv2 = cv2
            self.camera = cv2.VideoCapture(camera_id)
            if not self.camera.isOpened():
                logger.warning(f"Camera {camera_id} not found")
            else:
                logger.info(f"Camera {camera_id} initialized")
        except ImportError:
            logger.warning("OpenCV not available - camera disabled")

    def capture_photo(self, filename: str) -> bool:
        """Capture single photo"""
        try:
            if not self._camera or not self._camera.isOpened():
                logger.error("Camera not available")
                return False
            
            ret, frame = self._camera.read()
            if ret:
                self.cv2.imwrite(filename, frame)
                with self._lock:
                    self.total_photos += 1
                logger.info(f"Photo captured: {filename}")
                return True
            else:
                logger.error("Failed to capture frame")
                return False
                
        except Exception as e:
            logger.error(f"Photo capture failed: {str(e)}")
            return False

    def start_video_recording(self, filename: str) -> bool:
        """Start video recording"""
        try:
            if not self._camera or not self._camera.isOpened():
                logger.error("Camera not available")
                return False
            
            with self._lock:
                fourcc = self.cv2.VideoWriter_fourcc(*'mp4v')
                fps = int(self._camera.get(self.cv2.CAP_PROP_FPS))
                width = int(self._camera.get(self.cv2.CAP_PROP_FRAME_WIDTH))
                height = int(self._camera.get(self.cv2.CAP_PROP_FRAME_HEIGHT))
                
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

    def stop_video_recording(self) -> bool:
        """Stop video recording"""
        try:
            with self._lock:
                if self._video_writer:
                    self._video_writer.release()
                
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
                'is_recording': self.is_recording,
                'total_photos': self.total_photos,
                'total_video_time': self.total_video_time + current_record_time,
                'current_recording_time': current_record_time,
            }

    def cleanup(self):
        """Release camera"""
        try:
            if self.is_recording:
                self.stop_video_recording()
            if self._camera:
                self._camera.release()
            logger.info("Camera released")
        except Exception as e:
            logger.error(f"Error in camera cleanup: {str(e)}")


class PayloadController:
    """Master payload controller"""

    def __init__(self, config):
        self.spray_pump = SprayPump(config.spray_pump_pin)
        self.flow_sensor = FlowSensor(config.flow_sensor_pin) if config.flow_sensor_enabled else None
        self.camera = CameraController() if config.camera_enabled else None

    def arm_spray(self) -> bool:
        """Activate spray system"""
        if self.spray_pump.on():
            if self.flow_sensor:
                self.flow_sensor.start_monitoring()
            return True
        return False

    def disarm_spray(self) -> bool:
        """Deactivate spray system"""
        if self.flow_sensor:
            self.flow_sensor.stop_monitoring()
        return self.spray_pump.off()

    def get_payload_status(self) -> Dict:
        """Get all payload status"""
        status = {
            'spray_pump': self.spray_pump.get_status(),
        }
        
        if self.flow_sensor:
            status['flow_sensor'] = self.flow_sensor.get_status()
        
        if self.camera:
            status['camera'] = self.camera.get_status()
        
        return status

    def cleanup(self):
        """Cleanup all payloads"""
        self.disarm_spray()
        self.spray_pump.cleanup()
        
        if self.flow_sensor:
            self.flow_sensor.cleanup()
        
        if self.camera:
            self.camera.cleanup()
