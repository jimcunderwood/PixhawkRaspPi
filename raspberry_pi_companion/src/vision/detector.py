"""Optional edge obstacle detection using Coral TPU or YOLO."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    label: str
    confidence: float
    bbox: Dict[str, float]

    def to_dict(self) -> Dict:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "bbox": self.bbox,
        }


class EdgeObstacleDetector:
    """Load a model lazily and infer obstacles from the latest camera frame."""

    def __init__(self, config, frame_getter: Callable[[], object]):
        self.config = config
        self.frame_getter = frame_getter
        self._model = None
        self._backend = None
        self._labels: List[str] = []
        self._last_result: Optional[Dict] = None
        self._last_error: Optional[str] = None
        self._last_scan_at: Optional[float] = None

    def _load_labels(self) -> List[str]:
        labels_path = (self.config.labels_path or "").strip()
        if not labels_path:
            return []
        path = Path(labels_path)
        if not path.is_file():
            return []
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _load_coral(self):
        try:
            from tflite_runtime.interpreter import Interpreter  # type: ignore
        except Exception:
            return None

        model_path = (self.config.model_path or "").strip()
        if not model_path:
            return None

        try:
            interpreter = Interpreter(model_path=model_path)
            interpreter.allocate_tensors()
            self._backend = "coral"
            self._labels = self._load_labels()
            return interpreter
        except Exception as exc:
            self._last_error = f"Coral interpreter failed: {exc}"
            return None

    def _load_yolo(self):
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception:
            return None

        model_path = (self.config.model_path or "").strip()
        if not model_path:
            return None

        try:
            model = YOLO(model_path)
            self._backend = "yolo"
            self._labels = self._load_labels()
            return model
        except Exception as exc:
            self._last_error = f"YOLO model failed: {exc}"
            return None

    def initialize(self) -> Dict:
        backend = (self.config.backend or "auto").lower()
        candidates = [backend] if backend != "auto" else ["coral", "yolo"]
        self._model = None
        self._backend = None
        self._labels = self._load_labels()
        self._last_error = None

        for candidate in candidates:
            if candidate == "coral":
                self._model = self._load_coral()
            elif candidate == "yolo":
                self._model = self._load_yolo()
            else:
                continue
            if self._model is not None:
                break

        return self.get_status()

    def _frame_to_list(self, frame) -> Optional[object]:
        if frame is None:
            return None
        if hasattr(frame, "copy"):
            return frame.copy()
        return frame

    def _run_yolo(self, frame) -> List[Dict]:
        results = self._model.predict(
            source=frame,
            conf=self.config.confidence_threshold,
            iou=self.config.iou_threshold,
            imgsz=self.config.input_size,
            verbose=False,
        )
        detections: List[Dict] = []
        for result in results or []:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls_idx = int(box.cls[0]) if getattr(box, "cls", None) is not None else -1
                label = self._labels[cls_idx] if 0 <= cls_idx < len(self._labels) else str(cls_idx)
                xyxy = box.xyxy[0].tolist()
                detections.append(
                    DetectionResult(
                        label=label,
                        confidence=float(box.conf[0]),
                        bbox={"x1": xyxy[0], "y1": xyxy[1], "x2": xyxy[2], "y2": xyxy[3]},
                    ).to_dict()
                )
        return detections

    def _run_coral(self, frame) -> List[Dict]:
        try:
            from PIL import Image
        except Exception:
            return []

        try:
            from pycoral.adapters import common, detect  # type: ignore
            from pycoral.utils.dataset import read_label_file  # type: ignore
            from pycoral.utils.edgetpu import make_interpreter  # type: ignore
        except Exception:
            return []

        interpreter = self._model
        if interpreter is None:
            return []

        if not self._labels and self.config.labels_path:
            try:
                self._labels = list(read_label_file(self.config.labels_path).values())
            except Exception:
                self._labels = []

        rgb = frame
        if hasattr(frame, "shape") and len(frame.shape) == 3:
            # OpenCV frames are BGR; convert lazily if cv2 is available.
            try:
                import cv2

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            except Exception:
                rgb = frame

        image = Image.fromarray(rgb)
        common.set_resized_input(
            interpreter,
            image.size,
            lambda size: image.resize(size, Image.Resampling.LANCZOS),
        )
        interpreter.invoke()
        objs = detect.get_objects(interpreter, score_threshold=self.config.confidence_threshold)
        detections: List[Dict] = []
        for obj in objs:
            label = self._labels[obj.id] if 0 <= obj.id < len(self._labels) else str(obj.id)
            detections.append(
                DetectionResult(
                    label=label,
                    confidence=float(obj.score),
                    bbox={
                        "x1": float(obj.bbox.xmin),
                        "y1": float(obj.bbox.ymin),
                        "x2": float(obj.bbox.xmax),
                        "y2": float(obj.bbox.ymax),
                    },
                ).to_dict()
            )
        return detections

    def scan(self) -> Dict:
        now = time.time()
        frame = self._frame_to_list(self.frame_getter())
        if frame is None:
            self._last_error = "Camera frame unavailable."
            self._last_scan_at = now
            self._last_result = {
                "available": False,
                "backend": self._backend,
                "detections": [],
                "obstacle_risk": False,
                "scan_at": now,
                "error": self._last_error,
            }
            return self._last_result

        detections: List[Dict] = []
        try:
            if self._backend == "yolo" and self._model is not None:
                detections = self._run_yolo(frame)
            elif self._backend == "coral" and self._model is not None:
                detections = self._run_coral(frame)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Edge AI scan failed: %s", exc)

        obstacle_keywords = {
            keyword.strip().lower()
            for keyword in (self.config.obstacle_label_keywords or "").split(",")
            if keyword.strip()
        }
        obstacle_detections = [
            detection for detection in detections
            if any(keyword in detection["label"].lower() for keyword in obstacle_keywords)
            and detection["confidence"] >= self.config.confidence_threshold
        ]
        self._last_scan_at = now
        self._last_result = {
            "available": self._model is not None,
            "backend": self._backend,
            "detections": detections[: self.config.report_top_k],
            "obstacle_detections": obstacle_detections[: self.config.report_top_k],
            "obstacle_risk": bool(obstacle_detections),
            "scan_at": now,
            "error": self._last_error,
        }
        return self._last_result

    def get_status(self) -> Dict:
        return {
            "enabled": self.config.enabled,
            "backend": self._backend or self.config.backend,
            "configured": bool(self.config.enabled and (self.config.model_path or "").strip()),
            "model_path": self.config.model_path,
            "labels_path": self.config.labels_path,
            "confidence_threshold": self.config.confidence_threshold,
            "sample_interval_seconds": self.config.sample_interval_seconds,
            "last_scan_at": self._last_scan_at,
            "last_result": self._last_result,
            "last_error": self._last_error,
        }
