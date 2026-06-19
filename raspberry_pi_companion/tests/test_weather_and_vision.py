import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.vision.detector import EdgeObstacleDetector
from src.weather.service import WeatherService


class DummyWeatherConfig:
    enabled = False
    station_id = "KJFK"
    metar_url_template = ""
    taf_url_template = ""
    timeout_seconds = 1
    max_metar_age_minutes = 90
    min_visibility_sm = 3
    min_ceiling_ft = 1000
    max_wind_kt = 25
    max_gust_kt = 35
    allow_ifr = False
    blocking_hazards = "TS,FG,SN"


class DummyEdgeAiConfig:
    enabled = False
    backend = "auto"
    model_path = ""
    labels_path = ""
    input_size = 320
    confidence_threshold = 0.5
    iou_threshold = 0.45
    sample_interval_seconds = 0.5
    obstacle_label_keywords = "person,vehicle,tree,rock,obstacle"
    report_top_k = 5


def test_weather_briefing_flags_ifr_conditions():
    service = WeatherService(DummyWeatherConfig())
    briefing = service.build_briefing(
        station_id="KJFK",
        metar_raw="METAR KJFK 181651Z 18008KT 1SM BKN008 OVC015 18/16 A2992 RMK AO2",
        taf_raw="TAF KJFK 181720Z 1818/1924 18010KT P6SM BKN012",
    )

    assert briefing.ready is False
    assert any("Visibility" in reason for reason in briefing.blocking_reasons)
    assert briefing.metar["flight_category"] == "IFR"


def test_edge_detector_returns_safe_status_without_model():
    detector = EdgeObstacleDetector(DummyEdgeAiConfig(), frame_getter=lambda: None)

    status = detector.scan()

    assert status["available"] is False
    assert status["obstacle_risk"] is False
    assert status["detections"] == []
