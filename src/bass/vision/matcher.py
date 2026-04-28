"""Multi-scale template matching driven by ``assets/regions.yaml``.

Design goals
------------
* No hard dependency on OpenCV at import time – tests for the *region loader*
  and structural pieces should run without it. The actual matching imports
  cv2/numpy lazily.
* A single match per template is returned (top score across all scales).
* ROI clipping is applied in *device* coordinates (caller pre-scales ROIs from
  base resolution if needed).

A "region" entry has the following optional fields:

```yaml
templates:
  group/name:
    roi: [x, y, w, h]    # search window in base resolution
    threshold: 0.85      # override default
```
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateRegion:
    """Per-template configuration."""

    name: str  # e.g. "battle/sortie"
    roi: tuple[int, int, int, int] | None = None  # (x, y, w, h) in base resolution
    threshold: float | None = None


@dataclass(frozen=True)
class RegionConfig:
    default_threshold: float
    regions: dict[str, TemplateRegion]

    def get(self, name: str) -> TemplateRegion:
        if name in self.regions:
            return self.regions[name]
        return TemplateRegion(name=name, roi=None, threshold=None)


@dataclass(frozen=True)
class MatchResult:
    """Result of a single template match."""

    name: str
    found: bool
    score: float
    # Center of the match in the *frame* coordinate system (i.e. device pixels).
    center: tuple[int, int]
    # Bounding box (x, y, w, h) in the frame coordinate system.
    bbox: tuple[int, int, int, int]
    scale: float = 1.0

    def __bool__(self) -> bool:
        return self.found


# ---------------------------------------------------------------------------
# Region YAML loader
# ---------------------------------------------------------------------------


def load_regions(path: str | Path) -> RegionConfig:
    """Parse ``assets/regions.yaml`` into a :class:`RegionConfig`.

    The YAML grammar is intentionally permissive – an empty file is fine.
    """
    p = Path(path)
    if not p.exists():
        return RegionConfig(default_threshold=0.85, regions={})
    with p.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"regions file must be a mapping at root: {p}")

    defaults = raw.get("defaults") or {}
    default_threshold = float(defaults.get("threshold", 0.85))

    regions: dict[str, TemplateRegion] = {}
    templates = raw.get("templates") or {}
    if not isinstance(templates, dict):
        raise ValueError("`templates` must be a mapping")
    for name, body in templates.items():
        body = body or {}
        if not isinstance(body, dict):
            raise ValueError(f"template entry {name!r} must be a mapping")
        roi_raw = body.get("roi")
        roi: tuple[int, int, int, int] | None = None
        if roi_raw is not None:
            if (
                not isinstance(roi_raw, (list, tuple))
                or len(roi_raw) != 4
                or not all(isinstance(v, (int, float)) for v in roi_raw)
            ):
                raise ValueError(f"`roi` for {name!r} must be a 4-tuple of numbers")
            x, y, w, h = (int(v) for v in roi_raw)
            if w <= 0 or h <= 0:
                raise ValueError(f"`roi` for {name!r} has non-positive width/height")
            roi = (x, y, w, h)
        threshold = body.get("threshold")
        if threshold is not None:
            threshold = float(threshold)
        regions[name] = TemplateRegion(name=name, roi=roi, threshold=threshold)

    return RegionConfig(default_threshold=default_threshold, regions=regions)


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


class TemplateMatcher:
    """Loads template images on demand and performs multi-scale matching.

    Templates are looked up under ``assets/templates/<name>.png``. Each template
    is read once and cached in memory.

    Parameters
    ----------
    templates_root:
        Directory containing the ``common/``, ``story/``, ``battle/``, ``menu/``
        sub-folders.
    regions:
        Loaded :class:`RegionConfig` (use :func:`load_regions`).
    scales:
        Multi-scale search factors. Defaults to ``(1.0,)`` – pass ``(0.9, 1.0, 1.1)``
        to be robust to slight resolution differences.
    base_resolution / device_resolution:
        When provided, ROIs are scaled from the base coordinate system to the
        device frame. Otherwise ROIs are used as-is (useful for tests).
    language:
        Optional language tag; if a localized template exists at
        ``<root>/<group>/<lang>/<file>.png`` it is preferred.
    """

    def __init__(
        self,
        templates_root: str | Path,
        regions: RegionConfig,
        *,
        scales: tuple[float, ...] = (1.0,),
        base_resolution: tuple[int, int] | None = None,
        device_resolution: tuple[int, int] | None = None,
        language: str | None = None,
    ) -> None:
        self.templates_root = Path(templates_root)
        self.regions = regions
        self.scales = tuple(scales) if scales else (1.0,)
        self.base_resolution = base_resolution
        self.device_resolution = device_resolution
        self.language = language
        self._cache: dict[str, Any] = {}

    # ----------------------------- helpers -----------------------------
    def _scale_xy(self) -> tuple[float, float]:
        if self.base_resolution and self.device_resolution:
            bw, bh = self.base_resolution
            dw, dh = self.device_resolution
            if bw <= 0 or bh <= 0:
                return 1.0, 1.0
            return dw / bw, dh / bh
        return 1.0, 1.0

    def _resolve_template_path(self, name: str) -> Path | None:
        # name like "battle/sortie"
        group, fname = name.split("/", 1) if "/" in name else ("", name)
        candidates: list[Path] = []
        if self.language:
            candidates.append(self.templates_root / group / self.language / f"{fname}.png")
        candidates.append(self.templates_root / group / f"{fname}.png")
        for c in candidates:
            if c.is_file():
                return c
        return None

    def _load_template(self, name: str):
        if name in self._cache:
            return self._cache[name]
        import cv2  # type: ignore[import-not-found]

        path = self._resolve_template_path(name)
        if path is None:
            self._cache[name] = None
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            self._cache[name] = None
            return None
        self._cache[name] = img
        return img

    def _device_roi(self, region: TemplateRegion, frame_shape) -> tuple[int, int, int, int] | None:
        if region.roi is None:
            return None
        sx, sy = self._scale_xy()
        x, y, w, h = region.roi
        rx, ry = int(round(x * sx)), int(round(y * sy))
        rw, rh = int(round(w * sx)), int(round(h * sy))
        # Clip to frame
        H, W = frame_shape[:2]
        rx = max(0, min(rx, W - 1))
        ry = max(0, min(ry, H - 1))
        rw = max(1, min(rw, W - rx))
        rh = max(1, min(rh, H - ry))
        return rx, ry, rw, rh

    # ----------------------------- public ------------------------------
    def threshold_for(self, name: str) -> float:
        region = self.regions.get(name)
        if region.threshold is not None:
            return region.threshold
        return self.regions.default_threshold

    def match(self, frame, name: str, *, threshold: float | None = None) -> MatchResult:
        """Match a single template against ``frame``.

        ``frame`` must be a BGR ndarray (e.g. from
        :func:`bass.vision.capture.bytes_to_ndarray`).
        """
        import cv2  # type: ignore[import-not-found]

        thr = threshold if threshold is not None else self.threshold_for(name)
        region = self.regions.get(name)
        roi = self._device_roi(region, frame.shape)
        search = frame
        ox, oy = 0, 0
        if roi is not None:
            x, y, w, h = roi
            search = frame[y : y + h, x : x + w]
            ox, oy = x, y

        template = self._load_template(name)
        if template is None:
            return MatchResult(
                name=name, found=False, score=0.0, center=(0, 0), bbox=(0, 0, 0, 0)
            )

        # Scale the *template* to compensate for resolution differences and
        # the multi-scale sweep.
        sx, sy = self._scale_xy()
        base_scale = min(sx, sy)
        best: MatchResult = MatchResult(
            name=name, found=False, score=-1.0, center=(0, 0), bbox=(0, 0, 0, 0)
        )

        for s in self.scales:
            scale = base_scale * s
            th, tw = template.shape[:2]
            new_w = max(1, int(round(tw * scale)))
            new_h = max(1, int(round(th * scale)))
            if new_w >= search.shape[1] or new_h >= search.shape[0]:
                continue
            tmpl = cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_AREA)
            try:
                res = cv2.matchTemplate(search, tmpl, cv2.TM_CCOEFF_NORMED)
            except cv2.error:
                continue
            _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res)
            if max_v > best.score:
                cx = ox + max_l[0] + new_w // 2
                cy = oy + max_l[1] + new_h // 2
                best = MatchResult(
                    name=name,
                    found=False,
                    score=float(max_v),
                    center=(cx, cy),
                    bbox=(ox + max_l[0], oy + max_l[1], new_w, new_h),
                    scale=scale,
                )

        if best.score >= thr:
            best = MatchResult(
                name=best.name,
                found=True,
                score=best.score,
                center=best.center,
                bbox=best.bbox,
                scale=best.scale,
            )
        return best

    def match_any(self, frame, names: list[str]) -> dict[str, MatchResult]:
        return {n: self.match(frame, n) for n in names}

    def first_found(self, frame, names: list[str]) -> MatchResult | None:
        for n in names:
            m = self.match(frame, n)
            if m.found:
                return m
        return None
