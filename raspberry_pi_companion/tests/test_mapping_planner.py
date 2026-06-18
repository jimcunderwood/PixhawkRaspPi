"""Tests for photogrammetry and mapping helpers."""

import csv
import os
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.mapping.planner import (
    CameraSpec,
    GeotagRecord,
    MappingPlanner,
    PointCloudScanConfig,
    SurveyGridConfig,
    VegetationCaptureProfile,
)
from src.missions.planner import FieldBoundary, GeoPoint, MissionPlanner


class TestMappingPlanner:
    def setup_method(self):
        self.camera = CameraSpec(
            sensor_width_mm=13.2,
            sensor_height_mm=8.8,
            image_width_px=4000,
            image_height_px=3000,
            focal_length_mm=8.8,
        )
        self.planner = MappingPlanner(self.camera)

    def test_gsd_round_trip(self):
        altitude = self.planner.estimate_altitude_for_gsd(2.5)
        gsd = self.planner.estimate_gsd_cm(altitude)
        assert altitude == pytest.approx(66.67, rel=1e-2)
        assert gsd == pytest.approx(2.5, rel=1e-2)

    def test_survey_grid_generation(self):
        boundary = FieldBoundary(
            "Test Field",
            [
                GeoPoint(40.0000, -74.0000),
                GeoPoint(40.0000, -73.9990),
                GeoPoint(40.0010, -73.9990),
                GeoPoint(40.0010, -74.0000),
            ],
            altitude=12.0,
        )
        grid = self.planner.generate_survey_grid(
            boundary,
            SurveyGridConfig(
                front_overlap=0.7,
                side_overlap=0.8,
                target_gsd_cm=2.5,
                flight_speed_mps=5.0,
                line_heading_deg=15.0,
            ),
        )

        assert grid.waypoints
        assert grid.altitude_agl_m > 0
        assert grid.capture_interval_s > 0
        assert grid.line_spacing_m > 0
        assert grid.estimated_photo_count >= 1

    def test_geotag_csv_and_timestamp_sync(self, tmp_path):
        records = [
            GeotagRecord(
                filename="img_0001.jpg",
                latitude=40.1,
                longitude=-74.2,
                altitude_m=52.0,
                captured_at=1_700_000_000.0,
                trigger_timestamp=1_700_000_000.1,
                drone_id="drone-a",
            ),
            GeotagRecord(
                filename="img_0002.jpg",
                latitude=40.2,
                longitude=-74.1,
                altitude_m=54.0,
                captured_at=1_700_000_010.0,
                trigger_timestamp=1_700_000_010.1,
                drone_id="drone-a",
            ),
        ]
        synced = self.planner.synchronize_capture_timestamps(records, gps_time_offset_s=0.5)
        assert synced[0].gps_timestamp == pytest.approx(1_700_000_000.6)

        csv_path = self.planner.export_geotag_csv(synced, tmp_path / "geotags.csv")
        with csv_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))

        assert rows[0]["filename"] == "img_0001.jpg"
        assert rows[0]["drone_id"] == "drone-a"
        assert rows[0]["latitude"]
        assert rows[0]["longitude"]

    def test_write_geotagged_image(self, tmp_path):
        source = tmp_path / "source.jpg"
        target = tmp_path / "tagged.jpg"
        image = Image.new("RGB", (16, 16), color="white")
        image.save(source)

        record = GeotagRecord(
            filename=source.name,
            latitude=40.1234,
            longitude=-74.5678,
            altitude_m=80.0,
            captured_at=1_700_000_100.0,
            heading_deg=123.0,
        )

        output_path = self.planner.write_geotagged_image(source, record, target)
        assert output_path == target
        assert output_path.is_file()
        assert output_path.stat().st_size > 0

    def test_ndvi_and_false_color(self):
        red = np.array([[10, 20], [30, 40]], dtype=np.uint8)
        nir = np.array([[20, 30], [40, 50]], dtype=np.uint8)
        ndvi = self.planner.calculate_ndvi(red, nir)
        false_color = self.planner.ndvi_false_color(ndvi)

        assert ndvi.shape == red.shape
        assert np.all(ndvi > 0)
        assert false_color.shape[:2] == red.shape
        assert false_color.shape[2] == 3

    def test_real_time_ndvi(self):
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        frame[..., 0] = 10
        frame[..., 1] = 20
        profile = VegetationCaptureProfile(red_band_index=0, nir_band_index=1)
        ndvi = self.planner.compute_realtime_ndvi(frame, profile)
        assert ndvi.shape == (2, 2)

    def test_point_cloud_scan_generation(self):
        boundary = FieldBoundary(
            "Scan Field",
            [
                GeoPoint(40.0, -74.0),
                GeoPoint(40.0, -73.9995),
                GeoPoint(40.0005, -73.9995),
                GeoPoint(40.0005, -74.0),
            ],
            altitude=0.0,
        )
        points = self.planner.generate_point_cloud_scan(
            boundary,
            PointCloudScanConfig(enabled=True),
        )

        assert points
        assert len({point.altitude for point in points}) >= 1


class TestMissionPlannerMappingIntegration:
    def test_add_survey_grid_appends_waypoints(self):
        planner = MissionPlanner(max_waypoints=100)
        boundary = FieldBoundary(
            "Mapped Field",
            [
                GeoPoint(40.0, -74.0),
                GeoPoint(40.0, -73.9995),
                GeoPoint(40.0005, -73.9995),
                GeoPoint(40.0005, -74.0),
            ],
        )

        grid = planner.add_survey_grid(
            boundary,
            camera_spec={
                "sensor_width_mm": 13.2,
                "sensor_height_mm": 8.8,
                "image_width_px": 4000,
                "image_height_px": 3000,
                "focal_length_mm": 8.8,
            },
            survey_config={
                "front_overlap": 0.7,
                "side_overlap": 0.8,
                "target_gsd_cm": 2.5,
                "flight_speed_mps": 5.0,
            },
        )

        assert grid["waypoints"]
        assert len(planner.mission_items) == len(grid["waypoints"])
