"""Asset registry: maps logical state names to template file lists.

Naming conventions:
- xxx_full  = full screenshot including surrounding border/elements; xxx = tight crop.
- xxx_1 / xxx_2 = visual variants of the same element (color, gradient); all are tried.
- lock_xxx  = locked / inaccessible variant of an element.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

import cv2

from .vision import Template

log = logging.getLogger(__name__)

# Logical name → source file stems (no extension). Multiple files = multiple visual variants.
ASSET_GROUPS: Dict[str, List[str]] = {
    # --- Network / unexpected popups ---
    "network_reconnect": ["notice_reconnect"],
    "network_notice": ["notice_text"],
    # --- Combat ---
    "pause_continue": ["common_button_continue"],
    "combat_completed": ["combat_completed_confirm"],          # Win result confirm (bottom-right)
    "combat_failure": ["combat_failure_confirm"],              # Loss result confirm (bottom-center; needs a 2nd tap)
    "combat_completed_icon": ["combat_completed_icon_analyze"],  # Analyze icon always present on result screen
    "combat_mobilize": ["combat_mobilize_1", "combat_mobilize_2", "combat_mobilize_3"],
    "combat_auto_off": ["combat_auto_unenabled"],
    "combat_auto_on": ["combat_auto_enabled"],
    "combat_speed_1": ["combat_speed_1"],
    "combat_speed_2": ["combat_speed_2_1", "combat_speed_2_2"],
    "combat_speed_3": ["combat_speed_3", "combat_speed_3_2"],
    # --- Story playback ---
    "story_menu": ["story_menu_"],
    "story_menu_selected": ["story_menu_selected"],
    "story_auto": ["story_auto_1", "story_auto_2"],
    "story_skip": ["story_skip"],
    "story_skip_confirm": ["story_skip_confirm_1", "story_skip_confirm_2"],
    "story_skip_cancel": ["story_skip_cancel"],
    # --- Story list (not yet entered) ---
    "story_enter": [
        "story_enter_1",
        "story_enter_2",
        "story_enter_mini_1",
        "story_enter_mini_2",
    ],
    "story_enter_with_combat": ["story_enter_with_combat"],
    "story_enter_episode": ["story_enter_episode"],
    "story_icon_combat": ["story_icon_combat"],
    "next_page": ["story_next_page"],
    "story_cleared": ["story_cleared", "story_cleared_full"],
    "book_done": ["story_book_completed"],
    "book_undone": ["story_book_undone"],
    # --- Locked stages ---
    "lock": ["lock", "lock_combat", "lock_enter", "lock_enter_full"],
    # --- MomoTalk ---
    "momotalk_title": ["momotalk_title"],          # Pink "MomoTalk" title → confirms we are inside the popup
    "momotalk_reply": ["momotalk_reply"],          # "| Reply" label (appears only when reply options are available)
    "momotalk_reward": ["momotalk_reward"],        # "TOUCH TO CONTINUE" reward screen after a relationship story
    # Pink in-conversation "Relationship Story" button is detected by color, not template
    # (the button text contains the character's name in small font → unstable across characters).
    "momotalk_story_begin": ["momotalk_story_begin"],  # "Begin Relationship Story" teal button
    "momotalk_notice": ["momotalk_notice"],        # Notice (speaker) icon on home screen — anchor for MomoTalk entry
}

# Per-group confidence threshold overrides. Groups not listed use default_threshold.
THRESHOLD_OVERRIDES: Dict[str, float] = {
    # Wide text banner; score peak is narrow after scale refinement (~0.78-0.82).
    # Text is distinctive enough that false positives are not a concern → leave margin at 0.74.
    "story_cleared": 0.74,
    # Small icon; only matched while in COMBAT state (state machine isolation prevents false triggers
    # elsewhere), so the original author value is safe to keep.
    "combat_speed_1": 0.82,
    # Notice icon used as anchor; distinctive shape → 0.85 avoids false positives while tolerating lobby background variation.
    "momotalk_notice": 0.85,
    "momotalk_title": 0.85,
    # "TOUCH TO CONTINUE" is small text; peak is ~0.87. Use 0.80 to catch it as soon as it appears
    # (text is unique; false positive risk is negligible). Ensures priority-1 picks it up before
    # an inactivity timeout could fire.
    "momotalk_reward": 0.80,
    "momotalk_reply": 0.85,
}


def _load_template_gray(path: Path):
    """Load a template as grayscale. If the image has an alpha channel (polygon-cropped templates
    with transparent corners), fill transparent pixels with the mean grayscale value of opaque
    pixels so they are neutral under TM_CCOEFF_NORMED (mean-subtracted) and don't corrupt the
    match score. Returns the grayscale array, or None on failure."""
    import numpy as np

    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        bgr, alpha = img[:, :, :3], img[:, :, 3]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        opaque = alpha >= 128
        if opaque.any():
            fill = int(gray[opaque].mean())
            gray = gray.copy()
            gray[~opaque] = fill
        return gray
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def load_assets(assets_dir: str | Path) -> Dict[str, List[Template]]:
    """Load all group templates as grayscale. Missing files emit a warning but don't abort."""
    base = Path(assets_dir)
    groups: Dict[str, List[Template]] = {}
    for name, files in ASSET_GROUPS.items():
        templates: List[Template] = []
        for stem in files:
            path = base / f"{stem}.png"
            if not path.exists():
                log.warning("missing asset file: %s", path)
                continue
            gray = _load_template_gray(path)
            if gray is None:
                log.warning("cannot read asset file: %s", path)
                continue
            templates.append(Template(name=name, file=str(path), gray=gray))
        if not templates:
            log.warning("group '%s' has no usable template", name)
        groups[name] = templates
    return groups
