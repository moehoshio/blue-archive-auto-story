"""Config loading: reads config.yaml and provides typed config objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from dataclasses import fields as _dc_fields


@dataclass
class AdbConfig:
    path: str = "adb"
    serial: Optional[str] = None


@dataclass
class MatchingConfig:
    scale_min: float = 0.4
    scale_max: float = 2.0
    scale_steps: int = 17
    default_threshold: float = 0.80
    scale_cache_tolerance: float = 0.08
    # Resize the screen to this width before matching (cost ∝ pixel count); 0 = no resize.
    # Large UI elements lose no precision at 960px; speed gain ≈ (original/960)^2.
    proc_width: int = 960


@dataclass
class LoopConfig:
    tick_interval: float = 1.0
    tap_delay: float = 0.5
    idle_ticks_to_end: int = 30
    # Grace ticks after a state transition (action / state change): blank frames during this
    # window don't count toward the stuck counter (covers loading / animation gaps ~10s).
    # The stuck counter only starts accumulating once the grace window is exhausted.
    transition_grace_ticks: int = 8


@dataclass
class CombatConfig:
    desired_speed: int = 3


@dataclass
class NetworkConfig:
    max_reconnect: int = 10


@dataclass
class MomoTalkConfig:
    """MomoTalk automation parameters.

    Coordinates use the reference resolution (1920x1080) and are scaled linearly to
    the actual screen size at runtime (the popup layout is fixed, so this stays accurate
    across resolutions). Template matching is used for state detection and buttons;
    coordinate-based taps are used for the conversation list, tabs, and badge detection
    because those elements can't be reliably templated (avatar thumbnails, variable text,
    red-dot badge numbers)."""
    ref_width: int = 1920
    ref_height: int = 1080
    # Close button (X) in the top-right of the MomoTalk popup.
    close_xy: tuple = (1681, 177)
    # Home-screen positioning: instead of matching the MomoTalk icon directly (badge number
    # changes, background shifts with the lobby), we anchor on the Notice (speaker) icon
    # (momotalk_notice template — solid blue, fixed shape). MomoTalk entry = notice center
    # + this offset. The unread badge ROI is also relative to this anchor.
    notice_home_offset: tuple = (142, 10)
    # After reopening, the popup lands on the "Students" tab; click the "Unread" tab (left side).
    unread_tab_xy: tuple = (255, 430)
    # Center of the topmost conversation row in the unread list + per-row height + visible row count.
    first_row_xy: tuple = (450, 400)
    row_height: int = 105
    visible_rows: int = 5
    # Safe tap location on the reward screen's "TOUCH TO CONTINUE" (avoids tapping item icons).
    reward_dismiss_xy: tuple = (960, 1010)
    # Unread badge detection ROI relative to the MomoTalk entry center (x0,y0,x1,y1).
    # Red pixels in this box = still has unread conversations. Moves with the notice anchor,
    # so it stays correct even when the lobby background shifts.
    home_badge_rel: tuple = (12, -62, 52, -28)
    # Reply options: after the "| Reply" label (momotalk_reply template) is found, tap at
    # this fixed pixel offset from the label to hit the first reply option.
    # (With 1–2 options, the first one is always directly below-right of the label.)
    reply_label_offset: tuple = (200, 85)
    # Pink "Relationship Story" button in conversation: the text contains the character's name
    # in small font, making template matching unstable across characters (score 0.6–0.8).
    # Instead, color detection finds a sufficiently wide saturated-pink horizontal stripe in the ROI.
    # The title bar is also pink but is excluded by the y > 250 lower bound.
    # Values: HSV lower/upper bounds + minimum/maximum strip dimensions (reference pixels).
    story_enter_roi: tuple = (1100, 250, 1810, 965)
    story_enter_hsv_lo: tuple = (150, 50, 160)
    story_enter_hsv_hi: tuple = (180, 200, 255)
    story_enter_min_w: int = 250
    story_enter_min_h: int = 30
    story_enter_max_h: int = 95
    # Conversation activity detection ROI (right panel); average pixel difference between
    # two consecutive ticks above diff_thresh = new content (typing indicator or new message).
    convo_roi: tuple = (1100, 230, 1810, 950)
    diff_thresh: float = 2.0
    # Consecutive ticks with no conversation change and no actionable element → treat the
    # current conversation as finished and switch to the next unread.
    # "Typing…" animations typically resolve within 5 s; exceeding this means no new content.
    idle_switch_ticks: int = 5
    # Consecutive switches across visible rows with no progress → close and reopen MomoTalk
    # to refresh the list. Effective cap = min(max_switches, visible_rows - 1): only rows
    # 1..visible_rows-1 are tried (row 0 is the current conversation); on exhaustion, reopen.
    max_switches: int = 5
    # Require this many consecutive ticks with no unread badge before declaring the task done.
    # Prevents false positives from the brief moments when the badge disappears during a
    # story or reward transition (those gaps are only a few ticks; MomoTalk returns quickly).
    done_confirm_ticks: int = 6
    tap_delay: float = 0.6
    tick_interval: float = 1.0
    # Grace ticks after entering a story or reward screen (covers loading gaps).
    grace_ticks: int = 10


@dataclass
class Config:
    adb: AdbConfig = field(default_factory=AdbConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    combat: CombatConfig = field(default_factory=CombatConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    momotalk: MomoTalkConfig = field(default_factory=MomoTalkConfig)
    assets_dir: str = "assets"
    log_level: str = "INFO"
    save_debug_screens: bool = False

    @property
    def assets_path(self) -> Path:
        return Path(self.assets_dir)


def _build_momotalk(data: dict) -> MomoTalkConfig:
    """Apply YAML overrides to MomoTalkConfig; convert list values to tuples for coordinate fields."""
    valid = {f.name for f in _dc_fields(MomoTalkConfig)}
    kwargs = {}
    for k, v in data.items():
        if k not in valid:
            continue
        kwargs[k] = tuple(v) if isinstance(v, list) else v
    return MomoTalkConfig(**kwargs)


def load_config(path: str | Path = "config.yaml") -> Config:
    """Load YAML config; missing fields fall back to dataclass defaults."""
    data: dict = {}
    p = Path(path)
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    return Config(
        adb=AdbConfig(**(data.get("adb") or {})),
        matching=MatchingConfig(**(data.get("matching") or {})),
        loop=LoopConfig(**(data.get("loop") or {})),
        combat=CombatConfig(**(data.get("combat") or {})),
        network=NetworkConfig(**(data.get("network") or {})),
        momotalk=_build_momotalk(data.get("momotalk") or {}),
        assets_dir=data.get("assets_dir", "assets"),
        log_level=data.get("log_level", "INFO"),
        save_debug_screens=bool(data.get("save_debug_screens", False)),
    )
