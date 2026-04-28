"""Swipe action."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Action, ActionResult

if TYPE_CHECKING:  # pragma: no cover
    from ..device.adb_client import AdbClient


class SwipeAction(Action):
    def __init__(
        self, x1: int, y1: int, x2: int, y2: int, *, duration_ms: int = 300, name: str | None = None
    ) -> None:
        self.x1 = int(x1)
        self.y1 = int(y1)
        self.x2 = int(x2)
        self.y2 = int(y2)
        self.duration_ms = int(duration_ms)
        self.name = name or f"Swipe({x1},{y1}->{x2},{y2})"

    def execute(self, device: AdbClient) -> ActionResult:
        device.swipe(self.x1, self.y1, self.x2, self.y2, duration_ms=self.duration_ms)
        return ActionResult(ok=True)
