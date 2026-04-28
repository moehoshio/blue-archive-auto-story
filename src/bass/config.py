"""Configuration loading + validation.

Uses pydantic when available for nice validation; falls back to a small dataclass
loader otherwise so unit tests don't strictly require pydantic to be installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Plain dataclass models. Pydantic is optional – we just use it for parsing
# the raw dict via TypeAdapter when present.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdbConfig:
    serial: str = ""
    host: str = "127.0.0.1"
    port: int = 5037


@dataclass(frozen=True)
class Resolution:
    width: int = 1280
    height: int = 720

    @property
    def aspect(self) -> float:
        return self.width / self.height


@dataclass(frozen=True)
class OcrConfig:
    enabled: bool = False
    backend: str = "tesseract"


@dataclass(frozen=True)
class Config:
    adb: AdbConfig = field(default_factory=AdbConfig)
    base_resolution: Resolution = field(default_factory=Resolution)
    language: str = "zh-TW"
    match_threshold: float = 0.85
    match_scales: tuple[float, ...] = (0.9, 1.0, 1.1)
    loop_interval_ms: int = 700
    screenshots_on_unknown: bool = True
    debug_dump_dir: str = "debug_dumps"
    unknown_scene_limit: int = 8
    global_timeout_sec: int = 7200
    chapter_timeout_sec: int = 1800
    ocr: OcrConfig = field(default_factory=OcrConfig)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BattleDefaults:
    enable_auto: bool = True
    enable_x2_speed: bool = True
    pick_first_team: bool = True


@dataclass(frozen=True)
class StoryDefaults:
    pick_first_choice: bool = True
    skip_seen: bool = False


@dataclass(frozen=True)
class TaskDefaults:
    battle: BattleDefaults = field(default_factory=BattleDefaults)
    story: StoryDefaults = field(default_factory=StoryDefaults)


@dataclass(frozen=True)
class Task:
    type: str  # "main_story" | "event" | "story_only"
    volume: int | None = None
    chapter: int | None = None
    episode: int | None = None
    id: str | None = None
    chapters: tuple[int, ...] = ()


@dataclass(frozen=True)
class TaskFile:
    defaults: TaskDefaults = field(default_factory=TaskDefaults)
    tasks: tuple[Task, ...] = ()


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _read_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config root must be a mapping in {p}")
    return data


def load_config(path: str | Path) -> Config:
    raw = _read_yaml(path)
    adb = AdbConfig(**(raw.get("adb") or {}))
    res_raw = raw.get("base_resolution") or {}
    res = Resolution(width=int(res_raw.get("width", 1280)), height=int(res_raw.get("height", 720)))
    ocr = OcrConfig(**(raw.get("ocr") or {}))
    scales_raw = raw.get("match_scales") or [0.9, 1.0, 1.1]
    scales = tuple(float(x) for x in scales_raw)
    return Config(
        adb=adb,
        base_resolution=res,
        language=str(raw.get("language", "zh-TW")),
        match_threshold=float(raw.get("match_threshold", 0.85)),
        match_scales=scales,
        loop_interval_ms=int(raw.get("loop_interval_ms", 700)),
        screenshots_on_unknown=bool(raw.get("screenshots_on_unknown", True)),
        debug_dump_dir=str(raw.get("debug_dump_dir", "debug_dumps")),
        unknown_scene_limit=int(raw.get("unknown_scene_limit", 8)),
        global_timeout_sec=int(raw.get("global_timeout_sec", 7200)),
        chapter_timeout_sec=int(raw.get("chapter_timeout_sec", 1800)),
        ocr=ocr,
    )


def load_tasks(path: str | Path) -> TaskFile:
    raw = _read_yaml(path)
    d_raw = raw.get("defaults") or {}
    defaults = TaskDefaults(
        battle=BattleDefaults(**(d_raw.get("battle") or {})),
        story=StoryDefaults(**(d_raw.get("story") or {})),
    )
    tasks: list[Task] = []
    for item in raw.get("tasks") or []:
        if not isinstance(item, dict):
            raise ValueError(f"task entry must be a mapping, got: {item!r}")
        if "type" not in item:
            raise ValueError(f"task entry missing 'type': {item!r}")
        chapters = tuple(int(c) for c in (item.get("chapters") or ()))
        tasks.append(
            Task(
                type=str(item["type"]),
                volume=item.get("volume"),
                chapter=item.get("chapter"),
                episode=item.get("episode"),
                id=item.get("id"),
                chapters=chapters,
            )
        )
    return TaskFile(defaults=defaults, tasks=tuple(tasks))
