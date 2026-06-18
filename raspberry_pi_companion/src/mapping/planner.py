"""
Mapping and photogrammetry helpers.

The module keeps mapping-specific logic separate from the spray/mission logic,
but it is designed to plug into the existing mission planner and payload
controller. The implementation favors deterministic geometry and explicit
metadata so the ground station can use it on web, desktop, or mobile shells.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

import cv2
import numpy as np

try:
    from PIL import Image
    from PIL.TiffImagePlugin import IFDRational
except Exception:  # pragma: no cover - pillow is part of requirements but optional here
    Image = None
    IFDRational = Fraction

from src.missions.planner import FieldBoundary, GeoPoint


MetersPerDegreeLatitude = 111_320.0


def _meters_per_degree_longitude(latitude: float) -> float:
    return MetersPerDegreeLatitude * math.cos(math.radians(latitude))


def _decimal_to_dms(value: float) -> tuple[Fraction, Fraction, Fraction]:
    absolute = abs(value)
    degrees = int(absolute)
    minutes_full = (absolute - degrees) * 60.0
    minutes = int(minutes_full)
    seconds = round((minutes_full - minutes) * 60.0 * 10_000)
    return IFDRational(degrees, 1), IFDRational(minutes, 1), IFDRational(seconds, 10_000)

@dataclass
class CameraSpec:
    """Camera geometry used for photogrammetry planning."""

    sensor_width_mm: float
    sensor_height_mm: float
    image_width_px: int
    image_height_px: int
    focal_length_mm: float

    def gsd_cm_per_pixel(self, altitude_m: float) -> float:
        gsd_m = altitude_m * self.sensor_width_mm / (self.focal_length_mm * self.image_width_px)
        return gsd_m * 100.0

    def altitude_m_for_gsd(self, target_gsd_cm: float) -> float:
        target_gsd_m = target_gsd_cm / 100.0
        return target_gsd_m * self.focal_length_mm * self.image_width_px / self.sensor_width_mm

    def footprint_m(self, altitude_m: float) -> tuple[float, float]:
        width = altitude_m * self.sensor_width_mm / self.focal_length_mm
        height = altitude_m * self.sensor_height_mm / self.focal_length_mm
        return width, height

    def capture_interval_seconds(
        self,
        altitude_m: float,
        front_overlap: float,
        flight_speed_mps: float,
    ) -> float:
        _, footprint_height = self.footprint_m(altitude_m)
        usable_distance = footprint_height * (1.0 - front_overlap)
        if flight_speed_mps <= 0:
            return 0.0
        return usable_distance / flight_speed_mps

    def line_spacing_m(self, altitude_m: float, side_overlap: float) -> float:
        footprint_width, _ = self.footprint_m(altitude_m)
        return footprint_width * (1.0 - side_overlap)


@dataclass
class SurveyGridConfig:
    """Configuration for a photogrammetry survey grid."""

    front_overlap: float = 0.70
    side_overlap: float = 0.80
    target_gsd_cm: Optional[float] = None
    altitude_agl_m: Optional[float] = None
    flight_speed_mps: float = 5.0
    line_heading_deg: float = 0.0
    terrain_aware: bool = False
    terrain_clearance_m: float = 0.0
    border_margin_m: float = 0.0
    waypoint_spacing_m: Optional[float] = None
    trigger_latency_s: float = 0.0


@dataclass
class SurveyWaypoint:
    """Survey waypoint with optional capture metadata."""

    location: GeoPoint
    capture_image: bool = True
    trigger_index: Optional[int] = None
    altitude_agl_m: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "location": self.location.to_dict(),
            "capture_image": self.capture_image,
            "trigger_index": self.trigger_index,
            "altitude_agl_m": self.altitude_agl_m,
        }


@dataclass
class SurveyGridPlan:
    """Generated survey plan for orthomosaics or mapping passes."""

    waypoints: list[SurveyWaypoint] = field(default_factory=list)
    altitude_agl_m: float = 0.0
    gsd_cm_per_pixel: float = 0.0
    capture_interval_s: float = 0.0
    line_spacing_m: float = 0.0
    flight_heading_deg: float = 0.0
    photo_spacing_m: float = 0.0
    estimated_photo_count: int = 0

    def to_dict(self) -> dict:
        return {
            "waypoints": [waypoint.to_dict() for waypoint in self.waypoints],
            "altitude_agl_m": self.altitude_agl_m,
            "gsd_cm_per_pixel": self.gsd_cm_per_pixel,
            "capture_interval_s": self.capture_interval_s,
            "line_spacing_m": self.line_spacing_m,
            "flight_heading_deg": self.flight_heading_deg,
            "photo_spacing_m": self.photo_spacing_m,
            "estimated_photo_count": self.estimated_photo_count,
        }


@dataclass
class GeotagRecord:
    """Per-image geotag metadata for EXIF and CSV export."""

    filename: str
    latitude: float
    longitude: float
    altitude_m: float
    captured_at: float
    heading_deg: Optional[float] = None
    trigger_timestamp: Optional[float] = None
    gps_timestamp: Optional[float] = None
    drone_id: Optional[str] = None

    def to_csv_row(self) -> dict:
        captured_dt = datetime.fromtimestamp(self.captured_at, tz=timezone.utc)
        return {
            "filename": self.filename,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude_m": self.altitude_m,
            "captured_at_utc": captured_dt.isoformat(),
            "heading_deg": self.heading_deg,
            "trigger_timestamp": self.trigger_timestamp,
            "gps_timestamp": self.gps_timestamp,
            "drone_id": self.drone_id,
        }


@dataclass
class VegetationCaptureProfile:
    """Band layout used for NDVI and related indices."""

    red_band_index: int = 0
    nir_band_index: int = 1
    blue_band_index: Optional[int] = None
    green_band_index: Optional[int] = None
    camera_name: str = "multispectral"
    filter_name: str = "narrowband-nir"


@dataclass
class PreviewMosaicResult:
    """Low-resolution orthomosaic preview."""

    image: np.ndarray
    tile_count: int
    columns: int


@dataclass
class PointCloudScanConfig:
    """Planning hints for LiDAR and 3D scanning workflows."""

    enabled: bool = False
    altitude_levels_m: Sequence[float] = (30.0, 45.0, 60.0)
    orbit_radius_m: float = 25.0
    perimeter_margin_m: float = 5.0
    grid_spacing_m: float = 15.0
    include_center_pass: bool = True


class MappingPlanner:
    """High-level mapping helper for photogrammetry and scan planning."""

    def __init__(self, camera_spec: CameraSpec):
        self.camera_spec = camera_spec

    def estimate_altitude_for_gsd(self, target_gsd_cm: float) -> float:
        return self.camera_spec.altitude_m_for_gsd(target_gsd_cm)

    def estimate_gsd_cm(self, altitude_m: float) -> float:
        return self.camera_spec.gsd_cm_per_pixel(altitude_m)

    def calculate_capture_interval_s(self, altitude_m: float, config: SurveyGridConfig) -> float:
        return self.camera_spec.capture_interval_seconds(
            altitude_m=altitude_m,
            front_overlap=config.front_overlap,
            flight_speed_mps=config.flight_speed_mps,
        ) + max(0.0, config.trigger_latency_s)

    def calculate_line_spacing_m(self, altitude_m: float, config: SurveyGridConfig) -> float:
        return self.camera_spec.line_spacing_m(altitude_m, config.side_overlap)

    def generate_survey_grid(
        self,
        boundary: FieldBoundary,
        config: SurveyGridConfig,
        terrain_elevation_fn: Optional[Callable[[float, float], float]] = None,
    ) -> SurveyGridPlan:
        if len(boundary.vertices) < 3:
            raise ValueError("boundary must have at least 3 vertices")

        altitude_agl_m = config.altitude_agl_m
        if altitude_agl_m is None:
            if config.target_gsd_cm is None:
                altitude_agl_m = 60.0
            else:
                altitude_agl_m = self.estimate_altitude_for_gsd(config.target_gsd_cm)

        gsd_cm = self.estimate_gsd_cm(altitude_agl_m)
        capture_interval_s = self.calculate_capture_interval_s(altitude_agl_m, config)
        line_spacing_m = self.calculate_line_spacing_m(altitude_agl_m, config)
        photo_spacing_m = (
            self.camera_spec.footprint_m(altitude_agl_m)[1] * (1.0 - config.front_overlap)
        )

        centroid_lat = sum(vertex.latitude for vertex in boundary.vertices) / len(boundary.vertices)
        centroid_lon = sum(vertex.longitude for vertex in boundary.vertices) / len(boundary.vertices)
        meters_per_lon = _meters_per_degree_longitude(centroid_lat)

        local_vertices = [
            self._to_local(vertex.latitude, vertex.longitude, centroid_lat, centroid_lon, meters_per_lon)
            for vertex in boundary.vertices
        ]
        rotated_vertices = [self._rotate(point, -config.line_heading_deg) for point in local_vertices]
        min_x = min(x for x, _ in rotated_vertices) - config.border_margin_m
        max_x = max(x for x, _ in rotated_vertices) + config.border_margin_m
        min_y = min(y for _, y in rotated_vertices) - config.border_margin_m
        max_y = max(y for _, y in rotated_vertices) + config.border_margin_m

        line_positions = self._build_line_positions(min_y, max_y, line_spacing_m)
        waypoints: list[SurveyWaypoint] = []

        for line_index, line_y in enumerate(line_positions):
            x_start, x_end = (min_x, max_x) if line_index % 2 == 0 else (max_x, min_x)
            start_lat, start_lon = self._to_geo(
                *self._rotate((x_start, line_y), config.line_heading_deg),
                centroid_lat,
                centroid_lon,
                meters_per_lon,
            )
            end_lat, end_lon = self._to_geo(
                *self._rotate((x_end, line_y), config.line_heading_deg),
                centroid_lat,
                centroid_lon,
                meters_per_lon,
            )

            start_alt = altitude_agl_m
            end_alt = altitude_agl_m
            if config.terrain_aware and terrain_elevation_fn:
                start_alt += terrain_elevation_fn(start_lat, start_lon) + config.terrain_clearance_m
                end_alt += terrain_elevation_fn(end_lat, end_lon) + config.terrain_clearance_m
            else:
                start_alt += boundary.altitude + config.terrain_clearance_m
                end_alt += boundary.altitude + config.terrain_clearance_m

            waypoints.append(
                SurveyWaypoint(
                    location=GeoPoint(start_lat, start_lon, start_alt),
                    capture_image=True,
                    trigger_index=len(waypoints),
                    altitude_agl_m=altitude_agl_m,
                )
            )
            waypoints.append(
                SurveyWaypoint(
                    location=GeoPoint(end_lat, end_lon, end_alt),
                    capture_image=True,
                    trigger_index=len(waypoints),
                    altitude_agl_m=altitude_agl_m,
                )
            )

        estimated_photo_count = max(1, int(math.ceil(self._route_length_m(waypoints) / max(photo_spacing_m, 0.01))))

        return SurveyGridPlan(
            waypoints=waypoints,
            altitude_agl_m=altitude_agl_m,
            gsd_cm_per_pixel=gsd_cm,
            capture_interval_s=capture_interval_s,
            line_spacing_m=line_spacing_m,
            flight_heading_deg=config.line_heading_deg,
            photo_spacing_m=photo_spacing_m,
            estimated_photo_count=estimated_photo_count,
        )

    def write_geotagged_image(
        self,
        source_path: Path | str,
        record: GeotagRecord,
        output_path: Optional[Path | str] = None,
    ) -> Path:
        if Image is None:
            raise RuntimeError("Pillow is required to write EXIF geotags")

        source_path = Path(source_path)
        target_path = Path(output_path) if output_path else source_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(source_path) as image:
            exif = image.getexif()
            gps_ifd = self._build_gps_exif(record)
            exif[34853] = gps_ifd
            image.save(target_path, exif=exif)

        if output_path and source_path != target_path and source_path.is_file():
            # Preserve the original unless the caller explicitly overwrote it.
            pass

        return target_path

    def export_geotag_csv(self, records: Iterable[GeotagRecord], csv_path: Path | str) -> Path:
        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "filename",
                    "latitude",
                    "longitude",
                    "altitude_m",
                    "captured_at_utc",
                    "heading_deg",
                    "trigger_timestamp",
                    "gps_timestamp",
                    "drone_id",
                ],
            )
            writer.writeheader()
            for record in records:
                writer.writerow(record.to_csv_row())
        return csv_path

    def synchronize_capture_timestamps(
        self,
        records: Sequence[GeotagRecord],
        gps_time_offset_s: float = 0.0,
    ) -> list[GeotagRecord]:
        synchronized: list[GeotagRecord] = []
        for record in records:
            trigger_timestamp = record.trigger_timestamp or record.captured_at
            synchronized.append(
                GeotagRecord(
                    filename=record.filename,
                    latitude=record.latitude,
                    longitude=record.longitude,
                    altitude_m=record.altitude_m,
                    captured_at=trigger_timestamp + gps_time_offset_s,
                    heading_deg=record.heading_deg,
                    trigger_timestamp=trigger_timestamp,
                    gps_timestamp=trigger_timestamp + gps_time_offset_s,
                    drone_id=record.drone_id,
                )
            )
        return synchronized

    def calculate_ndvi(self, red: np.ndarray, nir: np.ndarray) -> np.ndarray:
        red = red.astype(np.float32)
        nir = nir.astype(np.float32)
        denominator = nir + red
        numerator = nir - red
        with np.errstate(divide="ignore", invalid="ignore"):
            ndvi = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator != 0)
        return np.clip(ndvi, -1.0, 1.0)

    def ndvi_false_color(self, ndvi: np.ndarray) -> np.ndarray:
        scaled = ((np.clip(ndvi, -1.0, 1.0) + 1.0) * 127.5).astype(np.uint8)
        return cv2.applyColorMap(scaled, cv2.COLORMAP_JET)

    def compute_realtime_ndvi(
        self,
        multi_band_frame: np.ndarray,
        profile: VegetationCaptureProfile,
    ) -> np.ndarray:
        red = multi_band_frame[..., profile.red_band_index]
        nir = multi_band_frame[..., profile.nir_band_index]
        return self.calculate_ndvi(red, nir)

    def build_preview_mosaic(
        self,
        image_paths: Sequence[Path | str],
        tile_scale: float = 0.2,
        columns: int = 4,
    ) -> PreviewMosaicResult:
        if Image is None:
            raise RuntimeError("Pillow is required to build orthomosaic previews")
        if columns <= 0:
            raise ValueError("columns must be positive")
        if not image_paths:
            raise ValueError("image_paths cannot be empty")

        tiles: list[np.ndarray] = []
        for path in image_paths:
            with Image.open(path) as image:
                rgb = image.convert("RGB")
                array = np.asarray(rgb)
                if tile_scale != 1.0:
                    new_size = (
                        max(1, int(array.shape[1] * tile_scale)),
                        max(1, int(array.shape[0] * tile_scale)),
                    )
                    array = cv2.resize(array, new_size, interpolation=cv2.INTER_AREA)
                tiles.append(array)

        tile_height = max(tile.shape[0] for tile in tiles)
        tile_width = max(tile.shape[1] for tile in tiles)
        rows = int(math.ceil(len(tiles) / columns))
        mosaic = np.zeros((rows * tile_height, columns * tile_width, 3), dtype=np.uint8)

        for index, tile in enumerate(tiles):
            row = index // columns
            column = index % columns
            y = row * tile_height
            x = column * tile_width
            mosaic[y:y + tile.shape[0], x:x + tile.shape[1]] = tile

        return PreviewMosaicResult(image=mosaic, tile_count=len(tiles), columns=columns)

    def generate_point_cloud_scan(
        self,
        boundary: FieldBoundary,
        config: PointCloudScanConfig,
    ) -> list[GeoPoint]:
        if len(boundary.vertices) < 3:
            raise ValueError("boundary must have at least 3 vertices")

        centroid_lat = sum(vertex.latitude for vertex in boundary.vertices) / len(boundary.vertices)
        centroid_lon = sum(vertex.longitude for vertex in boundary.vertices) / len(boundary.vertices)
        meters_per_lon = _meters_per_degree_longitude(centroid_lat)
        points: list[GeoPoint] = []

        if config.include_center_pass:
            for altitude in config.altitude_levels_m:
                points.append(GeoPoint(centroid_lat, centroid_lon, altitude))

        perimeter = self._build_perimeter_points(boundary, config.perimeter_margin_m)
        for altitude in config.altitude_levels_m:
            for lat, lon in perimeter:
                points.append(GeoPoint(lat, lon, altitude))

        if config.orbit_radius_m > 0:
            orbit_points = self._build_orbit_points(centroid_lat, centroid_lon, meters_per_lon, config.orbit_radius_m)
            for altitude in config.altitude_levels_m:
                for lat, lon in orbit_points:
                    points.append(GeoPoint(lat, lon, altitude))

        return points

    def _build_gps_exif(self, record: GeotagRecord) -> dict:
        gps_ifd = {
            1: "N" if record.latitude >= 0 else "S",
            2: _decimal_to_dms(record.latitude),
            3: "E" if record.longitude >= 0 else "W",
            4: _decimal_to_dms(record.longitude),
            5: 0 if record.altitude_m >= 0 else 1,
            6: IFDRational(int(abs(record.altitude_m) * 100), 100),
        }

        timestamp = record.gps_timestamp or record.captured_at
        if timestamp:
            moment = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            gps_ifd[7] = (
                IFDRational(moment.hour, 1),
                IFDRational(moment.minute, 1),
                IFDRational(moment.second, 1),
            )
            gps_ifd[29] = moment.strftime("%Y:%m:%d")

        if record.heading_deg is not None:
            gps_ifd[17] = IFDRational(int(record.heading_deg * 100), 100)

        return gps_ifd

    def _build_line_positions(self, min_y: float, max_y: float, line_spacing_m: float) -> list[float]:
        if line_spacing_m <= 0:
            return [(min_y + max_y) / 2.0]

        positions: list[float] = []
        cursor = min_y
        while cursor <= max_y + 1e-6:
            positions.append(cursor)
            cursor += line_spacing_m
        if positions[-1] < max_y:
            positions.append(max_y)
        return positions

    def _route_length_m(self, waypoints: Sequence[SurveyWaypoint]) -> float:
        total = 0.0
        for first, second in zip(waypoints, waypoints[1:]):
            total += self._distance_m(first.location, second.location)
        return total

    def _distance_m(self, first: GeoPoint, second: GeoPoint) -> float:
        avg_lat = (first.latitude + second.latitude) / 2.0
        lat_delta_m = (second.latitude - first.latitude) * MetersPerDegreeLatitude
        lon_delta_m = (second.longitude - first.longitude) * _meters_per_degree_longitude(avg_lat)
        alt_delta_m = second.altitude - first.altitude
        return math.sqrt(lat_delta_m**2 + lon_delta_m**2 + alt_delta_m**2)

    def _to_local(
        self,
        latitude: float,
        longitude: float,
        origin_latitude: float,
        origin_longitude: float,
        meters_per_lon: float,
    ) -> tuple[float, float]:
        x = (longitude - origin_longitude) * meters_per_lon
        y = (latitude - origin_latitude) * MetersPerDegreeLatitude
        return x, y

    def _to_geo(
        self,
        x: float,
        y: float,
        origin_latitude: float,
        origin_longitude: float,
        meters_per_lon: float,
    ) -> tuple[float, float]:
        latitude = origin_latitude + (y / MetersPerDegreeLatitude)
        longitude = origin_longitude + (x / meters_per_lon if meters_per_lon else 0.0)
        return latitude, longitude

    def _rotate(self, point: tuple[float, float], angle_deg: float) -> tuple[float, float]:
        x, y = point
        angle_rad = math.radians(angle_deg)
        cos_theta = math.cos(angle_rad)
        sin_theta = math.sin(angle_rad)
        return x * cos_theta - y * sin_theta, x * sin_theta + y * cos_theta

    def _build_perimeter_points(self, boundary: FieldBoundary, margin_m: float) -> list[tuple[float, float]]:
        centroid_lat = sum(vertex.latitude for vertex in boundary.vertices) / len(boundary.vertices)
        centroid_lon = sum(vertex.longitude for vertex in boundary.vertices) / len(boundary.vertices)
        meters_per_lon = _meters_per_degree_longitude(centroid_lat)
        local_vertices = [
            self._to_local(vertex.latitude, vertex.longitude, centroid_lat, centroid_lon, meters_per_lon)
            for vertex in boundary.vertices
        ]
        center_x = sum(x for x, _ in local_vertices) / len(local_vertices)
        center_y = sum(y for _, y in local_vertices) / len(local_vertices)
        if margin_m:
            perimeter = []
            for x, y in local_vertices:
                dx = x - center_x
                dy = y - center_y
                distance = math.sqrt(dx**2 + dy**2) or 1.0
                scale = (distance + margin_m) / distance
                perimeter.append((center_x + dx * scale, center_y + dy * scale))
        else:
            perimeter = local_vertices

        return [self._to_geo(x, y, centroid_lat, centroid_lon, meters_per_lon) for x, y in perimeter]

    def _build_orbit_points(
        self,
        center_lat: float,
        center_lon: float,
        meters_per_lon: float,
        radius_m: float,
        sample_count: int = 16,
    ) -> list[tuple[float, float]]:
        points = []
        for index in range(sample_count):
            angle = (2 * math.pi * index) / sample_count
            x = math.cos(angle) * radius_m
            y = math.sin(angle) * radius_m
            points.append(self._to_geo(x, y, center_lat, center_lon, meters_per_lon))
        return points


__all__ = [
    "CameraSpec",
    "GeotagRecord",
    "MappingPlanner",
    "MetersPerDegreeLatitude",
    "PointCloudScanConfig",
    "PreviewMosaicResult",
    "SurveyGridConfig",
    "SurveyGridPlan",
    "SurveyWaypoint",
    "VegetationCaptureProfile",
]
