"""元素資產註冊表: 邏輯狀態名 → 模板檔案清單。

命名規則 (見專案說明):
- xxx_full = 含外框/外部元素的完整截圖; xxx = 緊密裁切。
- xxx_1 / xxx_2 = 同一元素的不同樣式 (顏色/漸變), 匹配時逐一嘗試。
- lock_xxx = 鎖定/不可進入的變體。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

import cv2

from .vision import Template

log = logging.getLogger(__name__)

# 邏輯名 → 來源檔名 (不含副檔名)。同名多檔代表多樣式, 逐一嘗試。
ASSET_GROUPS: Dict[str, List[str]] = {
    # --- 網路/意外 ---
    "network_reconnect": ["notice_reconnect"],
    "network_notice": ["notice_text"],
    # --- 戰鬥 ---
    "pause_continue": ["common_button_continue"],
    "combat_completed": ["combat_completed_confirm"],          # 成功結算確認 (右下)
    "combat_failure": ["combat_failure_confirm"],              # 失敗結算確認 (中下, 需二次點擊)
    "combat_completed_icon": ["combat_completed_icon_analyze"],  # 結算頁必有的 analyze 圖標
    "combat_mobilize": ["combat_mobilize_1", "combat_mobilize_2", "combat_mobilize_3"],
    "combat_auto_off": ["combat_auto_unenabled"],
    "combat_auto_on": ["combat_auto_enabled"],
    "combat_speed_1": ["combat_speed_1"],
    "combat_speed_2": ["combat_speed_2_1", "combat_speed_2_2"],
    "combat_speed_3": ["combat_speed_3", "combat_speed_3_2"],
    # --- 劇情中 ---
    "story_menu": ["story_menu_"],
    "story_menu_selected": ["story_menu_selected"],
    "story_auto": ["story_auto_1", "story_auto_2"],
    "story_skip": ["story_skip"],
    "story_skip_confirm": ["story_skip_confirm_1", "story_skip_confirm_2"],
    "story_skip_cancel": ["story_skip_cancel"],
    # --- 故事列表頁 (未進入) ---
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
    # --- 鎖定 ---
    "lock": ["lock", "lock_combat", "lock_enter", "lock_enter_full"],
    # --- 好感劇情 (MomoTalk) ---
    "momotalk_title": ["momotalk_title"],          # 粉色 "MomoTalk" 標題 → 在彈窗內
    "momotalk_reply": ["momotalk_reply"],          # 對話右下「| Reply」標籤 (有回覆選項時才出現)
    "momotalk_reward": ["momotalk_reward"],        # 劇情後 "TOUCH TO CONTINUE" 領獎頁
    "momotalk_story_enter": ["momotalk_story_enter"],  # 對話中粉色 "Relationship Story" 按鈕
    "momotalk_story_begin": ["momotalk_story_begin"],  # "Begin Relationship Story" 青色按鈕
    "momotalk_home": ["momotalk_home"],            # 主畫面 MomoTalk 入口圖標 (重開用)
}

# 個別群組的匹配門檻覆寫 (純文字/小圖標可調)。未列者用 default_threshold。
THRESHOLD_OVERRIDES: Dict[str, float] = {
    # 寬文字橫幅, 尺度峰窄 (細化後約 0.78-0.82); 文字獨特, 誤判風險極低 → 留餘量。
    "story_cleared": 0.74,
    # combat_speed_1 是小圖標; 現在只在 IN_COMBAT 狀態比對 (狀態機隔離),
    # 不會再於非戰鬥畫面誤觸, 故沿用作者原值。
    "combat_speed_1": 0.82,
    # MomoTalk: home 圖標較小, 0.75 會在頂部狀態列誤咬 (~0.82); 提高門檻。
    # 且僅在主畫面 (momotalk_title 缺席) 才檢查, 雙重保險。
    "momotalk_home": 0.90,
    "momotalk_title": 0.85,
    "momotalk_reward": 0.85,
    "momotalk_reply": 0.85,
}


def _load_template_gray(path: Path):
    """讀取模板為灰階。若含 alpha (手繪多邊形裁切的透明角), 把透明像素填成
    不透明區的平均灰度, 使其在 TM_CCOEFF_NORMED (均值相減) 下趨近中性、
    不再以黑色破壞匹配。回傳 (gray, None) 或讀取失敗時 None。"""
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
    """載入所有群組模板 (灰階)。缺檔僅警告, 不中斷。"""
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
