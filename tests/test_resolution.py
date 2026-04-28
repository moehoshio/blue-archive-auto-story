"""Tests for device.resolution scaling helpers."""

from __future__ import annotations

from bass.device.resolution import CoordinateScaler


def test_scale_identity_when_resolutions_match() -> None:
    s = CoordinateScaler(1280, 720, 1280, 720)
    assert s.to_device(640, 360) == (640, 360)
    assert s.scale_roi((10, 20, 100, 50)) == (10, 20, 100, 50)
    assert s.template_scale == 1.0


def test_scale_to_device_for_1080p() -> None:
    s = CoordinateScaler(1280, 720, 1920, 1080)
    assert s.to_device(640, 360) == (960, 540)
    # Round-trip is approximate.
    rx, ry = s.to_device(640, 360)
    assert s.to_base(rx, ry) == (640, 360)
    # ROI scaling
    assert s.scale_roi((100, 100, 200, 200)) == (150, 150, 300, 300)
    assert s.template_scale == 1.5


def test_scale_to_device_for_unequal_aspect() -> None:
    s = CoordinateScaler(1280, 720, 1600, 720)
    # x stretched 1.25x, y unchanged.
    assert s.to_device(800, 360) == (1000, 360)
    # template_scale uses the smaller axis – here y.
    assert s.template_scale == 1.0
