"""Tests for the YAML config and tasks loaders."""

from __future__ import annotations

from pathlib import Path

import pytest

from bass.config import load_config, load_tasks


def test_load_config_minimal(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("language: en\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.language == "en"
    # Defaults still applied:
    assert cfg.match_threshold == 0.85
    assert cfg.base_resolution.width == 1280
    assert cfg.match_scales == (0.9, 1.0, 1.1)


def test_load_config_full(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(
        """
adb: { serial: "127.0.0.1:7555" }
base_resolution: { width: 1920, height: 1080 }
language: ja
match_threshold: 0.9
match_scales: [0.95, 1.0, 1.05]
loop_interval_ms: 500
unknown_scene_limit: 10
ocr: { enabled: true, backend: paddle }
""",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.adb.serial == "127.0.0.1:7555"
    assert cfg.base_resolution.width == 1920
    assert cfg.base_resolution.height == 1080
    assert cfg.match_threshold == 0.9
    assert cfg.match_scales == (0.95, 1.0, 1.05)
    assert cfg.loop_interval_ms == 500
    assert cfg.unknown_scene_limit == 10
    assert cfg.ocr.enabled is True
    assert cfg.ocr.backend == "paddle"


def test_load_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_load_tasks(tmp_path: Path) -> None:
    p = tmp_path / "tasks.yaml"
    p.write_text(
        """
defaults:
  battle: { enable_auto: false }
tasks:
  - { type: main_story, volume: 1, chapter: 3 }
  - { type: event, id: "2024_summer", chapters: [1, 2, 3] }
""",
        encoding="utf-8",
    )
    tf = load_tasks(p)
    assert tf.defaults.battle.enable_auto is False
    assert tf.defaults.battle.enable_x2_speed is True  # default
    assert len(tf.tasks) == 2
    assert tf.tasks[0].type == "main_story"
    assert tf.tasks[0].volume == 1
    assert tf.tasks[1].type == "event"
    assert tf.tasks[1].chapters == (1, 2, 3)


def test_load_tasks_rejects_missing_type(tmp_path: Path) -> None:
    p = tmp_path / "tasks.yaml"
    p.write_text("tasks:\n  - { id: x }\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_tasks(p)
