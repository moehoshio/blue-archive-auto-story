"""好感劇情 (MomoTalk) 自動化。

與主線劇情 (automator.py) 不同的獨立任務: 把每個未讀對話跑完 —— 回覆選項、進入並
跳過附帶的好感劇情 (Relationship Story)、領獎, 然後切換下一個未讀; 當前列表跑完 (連續
切換無進展) 就關閉並重開 MomoTalk 以刷新列表; 重開後已無未讀 (主畫面紅點消失) → 結束。

畫面流程 (實測):
  對話 ──回覆選項──▶ (對方輸入中→新訊息) ──▶ 出現「Relationship Event / Relationship
  Story」粉色按鈕 ──▶「Begin Relationship Story」──▶ 一般劇情 (Auto/Menu, 沿用主線跳過)
  ──▶「TOUCH TO CONTINUE」領獎頁 ──▶ 回到對話 (可能還有後續) ──▶ … ──▶ 無新內容。

辨識策略 (與主線一致地以模板為主, 但列表頭像/分頁/紅點無法穩定模板化, 故那些純位置點擊
用『參考解析度座標 × 實際縮放』):
  - 狀態判定/按鈕: momotalk_title / momotalk_reward / momotalk_story_enter /
    momotalk_story_begin / momotalk_home + 主線的 story_menu/story_skip/...。
  - 回覆選項框: 對話右下的亮色圓角塊, 以灰階亮度輪廓動態定位 (選項文字每次不同, 無法模板)。
  - 「對方輸入中/有新內容」: 對話面板兩 tick 的平均差 (輸入動畫/新訊息都會讓面板變動);
    面板靜止且無任何可操作元素達 idle_switch_ticks → 當前對話結束。
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Optional, Tuple

import cv2
import numpy as np

from . import notify
from .adb import Adb
from .assets import THRESHOLD_OVERRIDES, load_assets
from .config import Config
from .vision import Match, TemplateMatcher, to_gray

log = logging.getLogger(__name__)


class MomoStop(str, Enum):
    DONE = "no unread left, momotalk finished"
    STUCK = "no progress for too long, manual help needed"
    INTERRUPTED = "interrupted by user"


class MomoTalkAutomator:
    def __init__(self, cfg: Config, adb: Adb):
        self.cfg = cfg
        self.mt = cfg.momotalk
        self.adb = adb
        self.matcher = TemplateMatcher(cfg.matching)
        self.groups = load_assets(cfg.assets_dir)

        self._gray = None
        self._find_cache: dict = {}
        self._prev_convo: Optional[np.ndarray] = None  # 上一 tick 的對話面板 (灰階, 偵測變化)
        self._idle = 0              # 對話無變化且無可操作元素的連續 tick 數
        self._switches = 0          # 自上次有進展以來的切換次數
        self._grace = 0             # 轉場 (進入劇情/領獎) 後的載入豁免
        self._sx = 1.0              # 實際寬 / 參考寬
        self._sy = 1.0

    # ---- 座標縮放 (參考 1920x1080 → 實際畫面) ----
    def _pt(self, xy) -> Tuple[int, int]:
        return int(xy[0] * self._sx), int(xy[1] * self._sy)

    def _box(self, roi) -> Tuple[int, int, int, int]:
        x0, y0, x1, y1 = roi
        return (int(x0 * self._sx), int(y0 * self._sy),
                int(x1 * self._sx), int(y1 * self._sy))

    # ---- 模板匹配 (沿用主線快取慣例) ----
    def _find(self, group: str, threshold: Optional[float] = None) -> Optional[Match]:
        key = (group, threshold)
        if key in self._find_cache:
            return self._find_cache[key]
        tpls = self.groups.get(group)
        if not tpls:
            self._find_cache[key] = None
            return None
        thr = threshold if threshold is not None else THRESHOLD_OVERRIDES.get(group)
        m = self.matcher.find(self._gray, tpls, thr)
        self._find_cache[key] = m
        return m

    def _present(self, group: str, threshold: Optional[float] = None) -> bool:
        return self._find(group, threshold) is not None

    # ---- 點擊 ----
    def _tap_xy(self, x: int, y: int, label: str) -> None:
        log.info("action: %-22s tap (%d,%d)", label, x, y)
        self.adb.tap(x, y)
        time.sleep(self.mt.tap_delay)

    def _tap(self, m: Match, label: str) -> None:
        log.info("action: %-22s tap (%d,%d) <%s score=%.2f>", label, m.x, m.y, m.file, m.score)
        self.adb.tap(m.x, m.y)
        time.sleep(self.mt.tap_delay)

    def _tap_ref(self, xy, label: str) -> None:
        x, y = self._pt(xy)
        self._tap_xy(x, y, label)

    # ---- 主迴圈 ----
    def run(self) -> MomoStop:
        self.adb.ensure_device()
        notify.enable_windows_ansi()
        bgr = self.adb.screencap()
        h, w = bgr.shape[:2]
        self._sx = w / self.mt.ref_width
        self._sy = h / self.mt.ref_height
        log.info("momotalk started. screen %dx%d (scale %.3f,%.3f). press Ctrl+C to stop.",
                 w, h, self._sx, self._sy)
        try:
            while True:
                reason = self._tick()
                if reason is not None:
                    if reason == MomoStop.DONE:
                        notify.manual("momotalk_done")
                    elif reason == MomoStop.STUCK:
                        notify.manual("stuck")
                    log.info("finished: %s", reason.value)
                    return reason
                time.sleep(self.mt.tick_interval)
        except KeyboardInterrupt:
            log.info("interrupt received.")
            return MomoStop.INTERRUPTED

    def _tick(self) -> Optional[MomoStop]:
        self._gray = to_gray(self.adb.screencap())
        self._find_cache = {}

        # 1) 領獎頁 (劇情跳過後): 點一下繼續。最高優先, 因為它會疊在 momotalk 之上。
        if self._present("momotalk_reward"):
            self._tap_ref(self.mt.reward_dismiss_xy, "reward continue")
            return self._progress()

        # 2) 一般劇情畫面 (好感劇情): 沿用主線跳過流程 (open menu → skip → confirm)。
        if self._in_story():
            self._skip_story_step()
            return self._progress()

        # 3) 好感劇情入口: 先「Begin Relationship Story」面板, 再對話中的粉色按鈕。
        m = self._find("momotalk_story_begin")
        if m:
            self._tap(m, "begin relationship story")
            return self._progress()
        m = self._find("momotalk_story_enter")
        if m:
            self._tap(m, "enter relationship story")
            return self._progress()

        # 4) 在 MomoTalk 對話視窗內。
        if self._present("momotalk_title"):
            return self._handle_convo()

        # 5) 不在對話視窗 (已關閉/在主畫面/轉場): 嘗試重開, 或判定結束。
        return self._handle_offscreen()

    def _progress(self) -> None:
        """有動作/進展: 清零 idle 與切換計數, 重置變化基準與豁免。"""
        self._idle = 0
        self._switches = 0
        self._prev_convo = None
        self._grace = self.mt.grace_ticks
        return None

    # ---- 劇情跳過 (重用主線模板) ----
    def _in_story(self) -> bool:
        return self._present("story_auto") and (
            self._present("story_menu") or self._present("story_menu_selected"))

    def _skip_story_step(self) -> None:
        m = self._find("story_skip_confirm")
        if m:
            self._tap(m, "skip confirm")
            return
        m = self._find("story_skip")
        if m:
            self._tap(m, "skip")
            return
        if self._present("story_menu_selected"):
            return  # 選單已開, 等 skip 鈕出現 (再點會收起)
        m = self._find("story_menu")
        if m:
            self._tap(m, "open menu")

    # ---- 對話處理 ----
    def _handle_convo(self) -> Optional[MomoStop]:
        # 有回覆選項 → 選第一個 (好感任意選即可)。
        label = self._find("momotalk_reply")
        if label is not None:
            dx, dy = self.mt.reply_label_offset
            x = label.x + int(dx * self._sx)
            y = label.y + int(dy * self._sy)
            self._tap_xy(x, y, "reply option")
            return self._progress()

        # 無可操作元素: 看對話面板是否在變動 (對方輸入中 / 新訊息陸續出現)。
        if self._convo_changed():
            self._idle = 0
            return None  # 有新內容, 等它跑完
        if self._grace > 0:
            self._grace -= 1
            return None
        self._idle += 1
        if self._idle < self.mt.idle_switch_ticks:
            return None

        # 當前對話無新內容 → 切換其他未讀。
        self._idle = 0
        self._switches += 1
        if self._switches > self.mt.max_switches:
            # 可見列表都跑過仍無進展 → 關閉重開以刷新 (下個 tick 走 offscreen 分支)。
            log.info("no progress after %d switches, reopening momotalk.", self._switches - 1)
            self._switches = 0
            self._tap_ref(self.mt.close_xy, "close (refresh)")
            self._grace = self.mt.grace_ticks
            return None
        self._switch_conversation()
        return None

    def _switch_conversation(self) -> None:
        """切到列表中另一個未讀對話 (點第 _switches 列; 第 0 列通常是當前對話)。"""
        idx = self._switches % max(1, self.mt.visible_rows)
        x = self.mt.first_row_xy[0]
        y = self.mt.first_row_xy[1] + idx * self.mt.row_height
        self._tap_ref((x, y), f"switch unread (row {idx})")
        self._prev_convo = None  # 換對話, 重置變化基準
        self._grace = self.mt.grace_ticks

    def _convo_changed(self) -> bool:
        """對話面板較上一 tick 是否有明顯變化 (對方輸入中動畫 / 新訊息)。"""
        x0, y0, x1, y1 = self._box(self.mt.convo_roi)
        cur = self._gray[y0:y1, x0:x1]
        prev = self._prev_convo
        self._prev_convo = cur
        if prev is None or prev.shape != cur.shape:
            return True  # 首次/換對話: 視為有變化, 先等一拍
        diff = float(cv2.absdiff(cur, prev).mean())
        return diff > self.mt.diff_thresh

    # ---- 不在對話視窗: 重開或結束 ----
    def _handle_offscreen(self) -> Optional[MomoStop]:
        m = self._find("momotalk_home")
        if m is None:
            # 轉場中 (關閉動畫/載入)。給豁免, 否則計入 idle, 過久判定卡住。
            if self._grace > 0:
                self._grace -= 1
                return None
            self._idle += 1
            if self._idle >= self.mt.idle_switch_ticks + self.mt.max_switches + 5:
                return MomoStop.STUCK
            return None
        # 在主畫面: 有紅點 → 仍有未讀, 重開; 無紅點 → 結束。
        if self._home_has_unread():
            self._tap(m, "reopen momotalk")
            time.sleep(self.mt.tap_delay)
            self._tap_ref(self.mt.unread_tab_xy, "unread tab")
            self._tap_ref(self.mt.first_row_xy, "open top unread")
            self._idle = 0
            self._switches = 0
            self._prev_convo = None
            self._grace = self.mt.grace_ticks
            return None
        return MomoStop.DONE

    def _home_has_unread(self) -> bool:
        """主畫面 MomoTalk 入口是否有紅點 (= 仍有未讀)。在紅點框內找飽和紅色像素。"""
        bgr = self.adb.screencap()
        x0, y0, x1, y1 = self._box(self.mt.home_badge_roi)
        patch = bgr[y0:y1, x0:x1]
        if patch.size == 0:
            return False
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 120, 120), (12, 255, 255)) | \
            cv2.inRange(hsv, (168, 120, 120), (180, 255, 255))
        return int(cv2.countNonZero(mask)) > patch.shape[0] * patch.shape[1] * 0.08
