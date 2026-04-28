"""Coordinate / template scaling between the authoring resolution and a real device.

Templates and tap coordinates are produced against ``base_resolution``. When the
device runs at a different resolution we scale x/y coordinates and template ROIs
proportionally. This keeps assets reusable across emulators with the same aspect.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoordinateScaler:
    base_width: int
    base_height: int
    device_width: int
    device_height: int

    @property
    def sx(self) -> float:
        return self.device_width / self.base_width

    @property
    def sy(self) -> float:
        return self.device_height / self.base_height

    def to_device(self, x: int | float, y: int | float) -> tuple[int, int]:
        return int(round(x * self.sx)), int(round(y * self.sy))

    def to_base(self, x: int | float, y: int | float) -> tuple[int, int]:
        return int(round(x / self.sx)), int(round(y / self.sy))

    def scale_roi(self, roi: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x, y, w, h = roi
        return (
            int(round(x * self.sx)),
            int(round(y * self.sy)),
            int(round(w * self.sx)),
            int(round(h * self.sy)),
        )

    @property
    def template_scale(self) -> float:
        """Uniform scale used when resizing template images (use the smaller axis)."""
        return min(self.sx, self.sy)
