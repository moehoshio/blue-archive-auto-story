"""視覺匹配: 多尺度模板匹配 (螢幕解析度可變動)。

兩項效能關鍵:
1. 匹配前把畫面 (與模板) 縮到 proc_width 寬再做 TM_CCOEFF_NORMED。matchTemplate
   成本正比於像素數, 1920→960 可快約 4 倍, 對大型 UI 元素精度無損。
2. 「每個模板」各自快取上次命中的縮放比例 (模板裁切時 zoom 不一, 原生尺度互異),
   下次優先只在其附近搜尋; 從未命中過的模板才做完整尺度掃描。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .config import MatchingConfig

log = logging.getLogger(__name__)


@dataclass
class Template:
    name: str          # 邏輯名稱 (可多檔共用)
    file: str          # 來源檔名
    gray: np.ndarray   # 灰階模板
    last_scale: Optional[float] = field(default=None)  # 上次命中的尺度 (per-template 快取)


@dataclass
class Match:
    name: str
    x: int             # 中心點 x (原始畫面座標)
    y: int             # 中心點 y
    w: int
    h: int
    score: float
    scale: float
    file: str


class TemplateMatcher:
    def __init__(self, cfg: MatchingConfig):
        self.cfg = cfg
        self._scales: List[float] = list(
            np.linspace(cfg.scale_min, cfg.scale_max, cfg.scale_steps)
        )
        self._step = (self._scales[1] - self._scales[0]) if len(self._scales) > 1 else 0.0
        # 全域觀測尺度帶: 任何模板成功命中後更新; 用來收窄『缺席模板』的全掃描範圍
        # (同一裝置上所有元素的縮放都落在相近的帶內)。
        self._seen_min: Optional[float] = None
        self._seen_max: Optional[float] = None

    def _note_scale(self, s: float) -> None:
        self._seen_min = s if self._seen_min is None else min(self._seen_min, s)
        self._seen_max = s if self._seen_max is None else max(self._seen_max, s)

    # ---- 尺度選擇 ----
    def _near(self, scale: float) -> List[float]:
        tol = self.cfg.scale_cache_tolerance
        near = [s for s in self._scales if abs(s - scale) <= tol]
        if not near:
            # 找最接近的一格
            near = [min(self._scales, key=lambda s: abs(s - scale))]
        return near

    def _full(self) -> List[float]:
        """完整掃描用的尺度。暖機後 (已觀測過命中尺度) 只掃觀測帶, 收窄缺席元素
        的掃描成本; 尚無觀測時用全範圍。各模板裁切 zoom 不一 → 原生尺度分散
        (實測 1.07~1.33), 故用『乘法式』寬裕邊界, 避免把較大/較小的模板排除掉。"""
        if self._seen_min is None:
            return self._scales
        # 此裝置實測元素原生尺度集中 1.05~1.16 (個別到 ~1.33); ±20% 已足夠涵蓋, 又能
        # 大幅收窄『缺席元素』冷掃的尺度數 (省下 loading 空白幀的成本)。已命中過的模板
        # 各自快取尺度, 不受此帶影響。
        lo, hi = self._seen_min / 1.20, self._seen_max * 1.20
        band = [s for s in self._scales if lo <= s <= hi]
        return band or self._scales

    # ---- 單模板掃描 (在已縮放的畫面上) ----
    def _scan(
        self, sp: np.ndarray, tpl: Template, scales: Sequence[float], proc: float
    ) -> Optional[Tuple[float, float, int, int, int, int]]:
        """在縮放後畫面 sp 上掃描模板。回傳 (score, scale, tlx, tly, tw, th),
        其中 tlx/tly 為『原始畫面』座標, tw/th 為原始尺寸的模板寬高。"""
        sph, spw = sp.shape[:2]
        th0, tw0 = tpl.gray.shape[:2]
        best = None
        for s in scales:
            # 在縮放後畫面上的模板尺寸
            tw_p, th_p = int(tw0 * s * proc), int(th0 * s * proc)
            if tw_p < 8 or th_p < 8 or tw_p > spw or th_p > sph:
                continue
            resized = cv2.resize(tpl.gray, (tw_p, th_p), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(sp, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if best is None or max_val > best[0]:
                # 還原成原始座標/尺寸
                tlx, tly = int(max_loc[0] / proc), int(max_loc[1] / proc)
                tw, th = int(tw0 * s), int(th0 * s)
                best = (max_val, s, tlx, tly, tw, th)
        return best

    def _coarse_match(
        self, sp: np.ndarray, tpl: Template, proc: float, thr: float
    ) -> Optional[Tuple[float, float, int, int, int, int]]:
        """粗略 (網格尺度) 匹配, 不做細化。回傳最佳 (score, scale, tlx, tly, tw, th)。

        已命中過的模板只在其快取尺度附近搜尋: 同一裝置解析度固定 → 元素尺度恆定,
        快取尺度附近找不到即代表『缺席』, 不再回掃完整尺度帶。這省下 loading 空白幀
        對每個缺席元素的昂貴全掃 (空白幀的主要成本來源)。即使元素其實在場但快取網格
        略偏, find() 仍會對勝出者做密集細化補回尖銳尺度峰。從未命中過的模板才全掃。"""
        if tpl.last_scale is not None:
            return self._scan(sp, tpl, self._near(tpl.last_scale), proc)
        return self._scan(sp, tpl, self._full(), proc)

    # ---- 對外 ----
    def find(
        self,
        screen_gray: np.ndarray,
        templates: Sequence[Template],
        threshold: Optional[float] = None,
    ) -> Optional[Match]:
        """在 screen 中尋找 templates 中任一模板, 回傳分數最高且過門檻者。

        先對所有模板做粗略網格匹配選出最佳候選, 只對該『勝出模板』在其尺度峰鄰域
        密集細化 (由粗到細)。寬文字模板的尺度峰極窄 (實測 "All Episodes cleared."
        橫幅: 1.08→0.61, 1.10→0.82, 1.12→0.55, 需 ~0.01 尺度解析度); 只細化勝者
        可兼顧精度與速度 (不對群組內每個模板都做 17 點細掃)。"""
        thr = self.cfg.default_threshold if threshold is None else threshold
        sh, sw = screen_gray.shape[:2]
        proc = 1.0
        if self.cfg.proc_width and sw > self.cfg.proc_width:
            proc = self.cfg.proc_width / sw
            sp = cv2.resize(screen_gray, (int(sw * proc), int(sh * proc)),
                            interpolation=cv2.INTER_AREA)
        else:
            sp = screen_gray

        # 粗掃每個模板; 只對『邊界』候選做密集細化 — 已遠高於門檻者本就會過 (免細化),
        # 明顯缺席者 (粗分很低) 也免。如此只在真正吃緊的寬文字模板上付出細化成本,
        # 又不會像「只細化粗分冠軍」那樣漏掉『粗分較低但細化後更高』的變體
        # (story_cleared_full 粗分高於 story_cleared, 但 story_cleared 細化後才達 0.82)。
        best_c = None
        best_tpl: Optional[Template] = None
        for tpl in templates:
            c = self._coarse_match(sp, tpl, proc, thr)
            if c is None:
                continue
            if self._step and thr - 0.30 <= c[0] < thr + 0.05:
                fine = list(np.linspace(c[1] - self._step, c[1] + self._step, 17))
                r = self._scan(sp, tpl, fine, proc)
                if r is not None and r[0] > c[0]:
                    c = r
            if best_c is None or c[0] > best_c[0]:
                best_c, best_tpl = c, tpl
        if best_c is None or best_c[0] < thr:
            return None
        score, scale, tlx, tly, tw, th = best_c
        best_tpl.last_scale = scale
        self._note_scale(scale)
        cx, cy = int(tlx + tw / 2), int(tly + th / 2)
        best = Match(best_tpl.name, cx, cy, tw, th, score, scale, best_tpl.file)
        return best

    def find_all(
        self,
        screen_gray: np.ndarray,
        templates: Sequence[Template],
        threshold: Optional[float] = None,
        min_dist_frac: float = 0.5,
    ) -> List[Match]:
        """回傳所有過門檻的匹配 (跨多模板), 經非極大抑制去重。用於需同時定位
        多個同類元素的情境 (如列表頁挑選最上方未鎖定的 enter)。"""
        thr = self.cfg.default_threshold if threshold is None else threshold
        sh, sw = screen_gray.shape[:2]
        proc = 1.0
        if self.cfg.proc_width and sw > self.cfg.proc_width:
            proc = self.cfg.proc_width / sw
            sp = cv2.resize(screen_gray, (int(sw * proc), int(sh * proc)),
                            interpolation=cv2.INTER_AREA)
        else:
            sp = screen_gray

        found: List[Match] = []
        for tpl in templates:
            scales = self._near(tpl.last_scale) if tpl.last_scale is not None else self._full()
            th0, tw0 = tpl.gray.shape[:2]
            for s in scales:
                tw_p, th_p = int(tw0 * s * proc), int(th0 * s * proc)
                if tw_p < 8 or th_p < 8 or tw_p > sp.shape[1] or th_p > sp.shape[0]:
                    continue
                resized = cv2.resize(tpl.gray, (tw_p, th_p), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(sp, resized, cv2.TM_CCOEFF_NORMED)
                ys, xs = np.where(res >= thr)
                tw, th = int(tw0 * s), int(th0 * s)
                for y, x in zip(ys.tolist(), xs.tolist()):
                    cx = int((x + tw_p / 2) / proc)
                    cy = int((y + th_p / 2) / proc)
                    found.append(Match(tpl.name, cx, cy, tw, th, float(res[y, x]), s, tpl.file))

        found.sort(key=lambda m: -m.score)
        kept: List[Match] = []
        for m in found:
            if all(abs(m.x - k.x) >= max(k.w, m.w) * min_dist_frac or
                   abs(m.y - k.y) >= max(k.h, m.h) * min_dist_frac for k in kept):
                kept.append(m)
        return kept

    def present(
        self,
        screen_gray: np.ndarray,
        templates: Sequence[Template],
        threshold: Optional[float] = None,
    ) -> bool:
        return self.find(screen_gray, templates, threshold) is not None


def to_gray(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
