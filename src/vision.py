"""Visual matching: multi-scale template matching for a variable-resolution screen.

Two performance keys:
1. Resize the screen (and templates) to proc_width before running TM_CCOEFF_NORMED.
   matchTemplate cost is proportional to pixel count; 1920→960 gives ~4x speedup
   with no precision loss for large UI elements.
2. Each template caches its last-successful scale (templates are cropped at different
   zoom levels so their native scales differ). On the next tick, only scales near the
   cached value are searched; templates that have never matched get a full-range scan.
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
    name: str          # Logical group name (multiple files may share one name)
    file: str          # Source file path
    gray: np.ndarray   # Grayscale template image
    last_scale: Optional[float] = field(default=None)  # Last successful scale (per-template cache)


@dataclass
class Match:
    name: str
    x: int             # Center x in original screen coordinates
    y: int             # Center y
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
        # Global observed scale band: updated on every successful match.
        # Used to narrow the full scan for absent templates (all elements on the same
        # device fall within a similar scale band).
        self._seen_min: Optional[float] = None
        self._seen_max: Optional[float] = None

    def _note_scale(self, s: float) -> None:
        self._seen_min = s if self._seen_min is None else min(self._seen_min, s)
        self._seen_max = s if self._seen_max is None else max(self._seen_max, s)

    # ---- Scale selection ----
    def _near(self, scale: float) -> List[float]:
        tol = self.cfg.scale_cache_tolerance
        near = [s for s in self._scales if abs(s - scale) <= tol]
        if not near:
            near = [min(self._scales, key=lambda s: abs(s - scale))]
        return near

    def _full(self) -> List[float]:
        """Scale list for a full scan. After warm-up (at least one observed hit scale),
        only scan the observed band to reduce cost for absent elements; full range before
        any hits. Templates are cropped at different zooms → native scales vary
        (observed ~1.07–1.33), so a multiplicative ±20% margin avoids excluding any template."""
        if self._seen_min is None:
            return self._scales
        lo, hi = self._seen_min / 1.20, self._seen_max * 1.20
        band = [s for s in self._scales if lo <= s <= hi]
        return band or self._scales

    # ---- Single-template scan (on the already-resized screen) ----
    def _scan(
        self, sp: np.ndarray, tpl: Template, scales: Sequence[float], proc: float
    ) -> Optional[Tuple[float, float, int, int, int, int]]:
        """Scan template against the resized screen sp. Returns (score, scale, tlx, tly, tw, th)
        where tlx/tly are coordinates in the *original* screen and tw/th are the template
        dimensions at the original scale."""
        sph, spw = sp.shape[:2]
        th0, tw0 = tpl.gray.shape[:2]
        best = None
        for s in scales:
            # Template size on the resized screen
            tw_p, th_p = int(tw0 * s * proc), int(th0 * s * proc)
            if tw_p < 8 or th_p < 8 or tw_p > spw or th_p > sph:
                continue
            resized = cv2.resize(tpl.gray, (tw_p, th_p), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(sp, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if best is None or max_val > best[0]:
                # Convert back to original screen coordinates / size
                tlx, tly = int(max_loc[0] / proc), int(max_loc[1] / proc)
                tw, th = int(tw0 * s), int(th0 * s)
                best = (max_val, s, tlx, tly, tw, th)
        return best

    def _coarse_match(
        self, sp: np.ndarray, tpl: Template, proc: float, thr: float
    ) -> Optional[Tuple[float, float, int, int, int, int]]:
        """Coarse (grid-scale) match without refinement. Returns the best
        (score, scale, tlx, tly, tw, th).

        Templates with a cached scale are only searched near that scale: on a fixed-resolution
        device the element's scale is constant, so failing within the cache band means absent —
        no need to fall back to the full range. This saves the expensive full scan on every
        absent element during blank loading frames (the main cost source for idle ticks).
        Templates that have never matched get a full scan. The winner is still refined in find()
        even if the coarse grid slightly misses the score peak."""
        if tpl.last_scale is not None:
            return self._scan(sp, tpl, self._near(tpl.last_scale), proc)
        return self._scan(sp, tpl, self._full(), proc)

    # ---- Public API ----
    def find(
        self,
        screen_gray: np.ndarray,
        templates: Sequence[Template],
        threshold: Optional[float] = None,
    ) -> Optional[Match]:
        """Find any of the given templates in screen_gray; return the highest-scoring match
        above threshold, or None.

        Coarse-scans all templates first, then densely refines only the winner near its scale
        peak (coarse-to-fine). Wide text banners have very sharp scale peaks (observed:
        "All Episodes cleared." at 1.08→0.61, 1.10→0.82, 1.12→0.55; needs ~0.01 resolution);
        refining only the winner is precise and fast. Refinement is applied to "borderline"
        candidates (coarse score within a window around threshold), so a variant with a lower
        coarse score but higher refined score is not missed."""
        thr = self.cfg.default_threshold if threshold is None else threshold
        sh, sw = screen_gray.shape[:2]
        proc = 1.0
        if self.cfg.proc_width and sw > self.cfg.proc_width:
            proc = self.cfg.proc_width / sw
            sp = cv2.resize(screen_gray, (int(sw * proc), int(sh * proc)),
                            interpolation=cv2.INTER_AREA)
        else:
            sp = screen_gray

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
        """Return all above-threshold matches (across all templates), deduplicated by
        non-maximum suppression. Used when multiple instances of the same element class
        need to be located simultaneously (e.g. picking the topmost unlocked enter button)."""
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
