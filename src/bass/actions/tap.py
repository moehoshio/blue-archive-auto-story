"""Tap actions: by absolute coordinates or by template-match center."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..utils.logging import log
from .base import Action, ActionResult

if TYPE_CHECKING:  # pragma: no cover
    from ..device.adb_client import AdbClient
    from ..vision.state_detector import SceneObservation


class TapAction(Action):
    """Tap a fixed coordinate (in *device* frame coordinates)."""

    def __init__(self, x: int, y: int, *, name: str | None = None) -> None:
        self.x = int(x)
        self.y = int(y)
        self.name = name or f"Tap({x},{y})"

    def execute(self, device: AdbClient) -> ActionResult:
        device.tap(self.x, self.y)
        return ActionResult(ok=True)


class TapTemplateAction(Action):
    """Tap the center of a previously-matched template.

    The action is only applicable if the named template was found in the most
    recent observation; otherwise :meth:`precondition` returns ``False`` and the
    engine skips it.
    """

    def __init__(self, template_name: str, *, name: str | None = None) -> None:
        self.template_name = template_name
        self.name = name or f"TapTemplate({template_name})"
        self._cached_xy: tuple[int, int] | None = None

    def precondition(self, observation: SceneObservation) -> bool:
        m = observation.get(self.template_name)
        if m is None or not m.found:
            self._cached_xy = None
            return False
        self._cached_xy = m.center
        return True

    def execute(self, device: AdbClient) -> ActionResult:
        if self._cached_xy is None:
            return ActionResult(ok=False, reason="template not matched")
        x, y = self._cached_xy
        log.debug(f"tap template {self.template_name} at ({x},{y})")
        device.tap(x, y)
        return ActionResult(ok=True)
