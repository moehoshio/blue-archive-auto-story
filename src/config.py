"""設定載入: 從 config.yaml 讀取並提供型別化的設定物件。"""
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
    # 匹配前把畫面縮到此寬度再比對 (成本∝像素數); 0 = 不縮。
    # 大型 UI 元素在 960 寬下精度無損, 速度約快 (orig/960)^2 倍。
    proc_width: int = 960


@dataclass
class LoopConfig:
    tick_interval: float = 1.0
    tap_delay: float = 0.5
    idle_ticks_to_end: int = 30
    # 流程變更 (動作/狀態轉移) 後的「豁免」ticks: 期間即使無任何匹配也不計入失敗數
    # (涵蓋載入/動畫空檔, 如戰鬥載入 ~10s)。豁免用完才開始累計 → STUCK。
    transition_grace_ticks: int = 8


@dataclass
class CombatConfig:
    desired_speed: int = 3


@dataclass
class NetworkConfig:
    max_reconnect: int = 10


@dataclass
class MomoTalkConfig:
    """好感劇情 (MomoTalk) 自動化參數。

    定位採『參考解析度 (1920x1080) 下的絕對座標』, 執行時依實際畫面寬高線性縮放
    (彈窗為固定版面, 縮放後在其他解析度仍對位)。劇情列表的頭像/分頁/紅點無法用
    模板穩定辨識, 故對話切換/重開等純位置點擊用座標, 狀態判定與按鈕用模板匹配。"""
    ref_width: int = 1920
    ref_height: int = 1080
    # 關閉彈窗的 X (右上)。
    close_xy: tuple = (1681, 177)
    # 主畫面 MomoTalk 入口 (重開用); 也用模板 momotalk_home 確認在主畫面。
    home_xy: tuple = (220, 220)
    # 重開後預設停在『學生』分頁; 需點左側『未讀訊息』分頁 (聊天氣泡圖標)。
    unread_tab_xy: tuple = (255, 430)
    # 未讀列表最上方對話列中心 + 每列高度 + 可見列數。
    first_row_xy: tuple = (450, 400)
    row_height: int = 105
    visible_rows: int = 5
    # 領獎頁『TOUCH TO CONTINUE』的安全點擊處 (避開可點的道具圖標)。
    reward_dismiss_xy: tuple = (960, 1010)
    # 主畫面 MomoTalk 入口紅點的偵測框 (有紅點=仍有未讀); ref 座標 (x0,y0,x1,y1)。
    home_badge_roi: tuple = (232, 158, 272, 192)
    # 回覆選項: 對話右下「| Reply」標籤 (momotalk_reply 模板) 命中後, 點其右下固定位移處
    # 的第一個選項 (1~2 個選項時第一個都在標籤正下方; 好感任意選即可)。位移為參考解析度像素。
    reply_label_offset: tuple = (200, 85)
    # 對話面板的變化偵測框 (右側); 兩 tick 平均差 > diff_thresh 視為有新內容 (對方輸入中/新訊息)。
    convo_roi: tuple = (1100, 230, 1810, 950)
    diff_thresh: float = 2.0
    # 連續多少 tick 對話無變化且無可操作元素 → 視為當前對話結束, 切換下一個未讀。
    idle_switch_ticks: int = 8
    # 連續切換這麼多次仍無進展 → 關閉並重開以刷新列表。
    max_switches: int = 5
    # 重開後紅點消失 (無未讀) → 任務結束。
    tap_delay: float = 0.6
    tick_interval: float = 1.0
    # 流程轉場 (進入劇情/領獎) 的載入空檔豁免 ticks。
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
    """以 YAML 覆寫 MomoTalkConfig; 座標欄位 (list) 一律轉成 tuple, 其餘原樣帶入。"""
    valid = {f.name for f in _dc_fields(MomoTalkConfig)}
    kwargs = {}
    for k, v in data.items():
        if k not in valid:
            continue
        kwargs[k] = tuple(v) if isinstance(v, list) else v
    return MomoTalkConfig(**kwargs)


def load_config(path: str | Path = "config.yaml") -> Config:
    """讀取 YAML 設定; 缺漏欄位以 dataclass 預設值補齊。"""
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
