import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.prescription.controller import PrescriptionMapConfig, PrescriptionMapStore, PrescriptionRateController


class DummyPrescriptionConfig:
    enabled = True
    swath_width_meters = 12.0
    default_rate_liters_per_hectare = 20.0
    minimum_rate_liters_per_hectare = 1.0
    maximum_rate_liters_per_hectare = 60.0
    minimum_speed_mps = 1.0
    maximum_speed_mps = 15.0
    synchronize_to_ground_speed = True


def test_geojson_prescription_map_evaluation(tmp_path):
    store = PrescriptionMapStore(PrescriptionMapConfig(path=tmp_path / "prescription.sqlite3"))
    controller = PrescriptionRateController(DummyPrescriptionConfig(), store)

    payload = {
        "id": "north-block",
        "name": "North Block",
        "description": "Test prescription",
        "properties": {
            "default_rate_lpha": 18.0,
            "swath_width_m": 14.0,
        },
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "label": "North edge",
                    "target_rate_lpha": 24.0,
                    "priority": 3,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-74.2132, 40.1120],
                            [-74.2120, 40.1120],
                            [-74.2120, 40.1130],
                            [-74.2132, 40.1130],
                            [-74.2132, 40.1120],
                        ]
                    ],
                },
            }
        ],
    }

    result = controller.import_payload(json.dumps(payload), "north-block", activate=True)
    assert result["active_map"]["map_id"] == "north-block"
    assert controller.get_status()["active_map"]["map_id"] == "north-block"

    evaluation = controller.evaluate(
        {
            "location": {"latitude": 40.1124, "longitude": -74.2126},
            "ground_speed": 4.0,
        }
    )

    assert evaluation["current_zone"]["label"] == "North edge"
    assert evaluation["target_rate_liters_per_hectare"] == 24.0
    assert evaluation["current_flow_rate_liters_per_minute"] > 0
    assert evaluation["recommended_duty_cycle"] is not None
