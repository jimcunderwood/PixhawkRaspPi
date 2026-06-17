"""
Tests for payload controller timing-sensitive hardware helpers.
"""

import os
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.payloads.controller import CameraController, CameraTrigger


def test_camera_trigger_uses_fractional_millisecond_pulse(monkeypatch):
    sleep_calls = []

    fake_gpio = types.SimpleNamespace(
        BCM="BCM",
        OUT="OUT",
        LOW=0,
        HIGH=1,
        setmode=lambda mode: None,
        setup=lambda pin, mode: None,
        output=lambda pin, value: None,
        cleanup=lambda pin=None: None,
    )
    fake_rpi = types.SimpleNamespace(GPIO=fake_gpio)
    monkeypatch.setitem(sys.modules, "RPi", fake_rpi)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", fake_gpio)
    monkeypatch.setattr("src.payloads.controller.time.sleep", lambda seconds: sleep_calls.append(seconds))

    trigger = CameraTrigger(gpio_pin=22, pulse_ms=0.5)
    result = trigger.trigger()

    assert result["pulse_ms"] == 0.5
    assert sleep_calls == [0.0005]


def test_build_video_recording_path_uses_session_folder(monkeypatch, tmp_path):
    monkeypatch.setattr("src.payloads.controller.time.strftime", lambda fmt: "20260101_120000")
    monkeypatch.setattr("src.payloads.controller.time.monotonic", lambda: 12.345)

    controller = object.__new__(CameraController)
    controller.photo_directory = Path(tmp_path)

    session_path = controller.build_video_recording_path(session="field-7")
    default_path = controller.build_video_recording_path()

    assert session_path.parent == Path(tmp_path) / "field-7" / "videos"
    assert session_path.name == "video_field-7_20260101_120000_12345.mp4"
    assert default_path.parent == Path(tmp_path) / "videos"
    assert default_path.name == "video_20260101_120000_12345.mp4"
