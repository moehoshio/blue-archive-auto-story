"""Action base class.

Actions are *intentionally small* – mostly tap/swipe/wait – so the engine can
compose them through Flows without each Action having to know the whole world.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ..device.adb_client import AdbClient
    from ..vision.state_detector import SceneObservation


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    reason: str = ""


class Action:
    """Abstract base class. Subclasses must override :meth:`execute`."""

    name: str = "Action"

    # Optional – default to "always applicable".
    def precondition(self, observation: SceneObservation) -> bool:  # noqa: D401
        return True

    def execute(self, device: AdbClient) -> ActionResult:  # pragma: no cover
        raise NotImplementedError

    # Optional – default to "no verification".
    def postcondition(
        self, observation: SceneObservation
    ) -> bool:  # noqa: D401  pragma: no cover
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.name}>"


class FunctionAction(Action):
    """Wrap a plain function as an Action – handy for one-off scripted steps."""

    def __init__(
        self,
        name: str,
        fn: Callable[[AdbClient], ActionResult | None],
        *,
        precondition: Callable[[SceneObservation], bool] | None = None,
    ) -> None:
        self.name = name
        self._fn = fn
        self._pre = precondition

    def precondition(self, observation: SceneObservation) -> bool:
        return self._pre(observation) if self._pre else True

    def execute(self, device: AdbClient) -> ActionResult:
        result = self._fn(device)
        return result if isinstance(result, ActionResult) else ActionResult(ok=True)
