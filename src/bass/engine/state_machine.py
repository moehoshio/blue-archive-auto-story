"""Main observe-decide-act loop.

The state machine is intentionally generic: it consumes an iterable of *Flows*
(objects with a ``decide(observation) -> list[Action]`` method, optionally a
``is_terminal(observation)``). Higher layers configure which flows to run for
which task type.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ..utils.logging import log
from ..vision.state_detector import SceneObservation, SceneState

if TYPE_CHECKING:  # pragma: no cover
    from ..actions.base import Action
    from ..device.adb_client import AdbClient
    from ..vision.state_detector import StateDetector


class _Flow(Protocol):  # pragma: no cover
    def decide(self, observation: SceneObservation) -> list[Action]: ...


@dataclass
class EngineConfig:
    loop_interval_ms: int = 700
    unknown_scene_limit: int = 8
    chapter_timeout_sec: int = 1800
    screenshots_on_unknown: bool = True
    debug_dump_dir: str = "debug_dumps"


@dataclass
class StateMachine:
    device: AdbClient
    detector: StateDetector
    flows: list[_Flow] = field(default_factory=list)
    config: EngineConfig = field(default_factory=EngineConfig)

    _stop_requested: bool = False
    _unknown_streak: int = 0

    def __post_init__(self) -> None:
        self._install_signal_handlers()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def request_stop(self) -> None:
        self._stop_requested = True

    def _install_signal_handlers(self) -> None:
        def handler(signum, _frame):  # noqa: ANN001
            log.warning(f"signal {signum} received – requesting stop")
            self.request_stop()

        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except Exception:  # pragma: no cover  – e.g. on threads
            pass

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def _dump_unknown(self, frame) -> None:
        if not self.config.screenshots_on_unknown:
            return
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover
            return
        out = Path(self.config.debug_dump_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = out / f"unknown-{ts}.png"
        cv2.imwrite(str(path), frame)
        log.warning(f"dumped UNKNOWN screen to {path}")

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------
    def run_until(
        self,
        is_done: callable[[SceneObservation], bool],  # noqa: F821
        *,
        max_seconds: int | None = None,
    ) -> SceneObservation:
        """Run until ``is_done(observation)`` returns truthy or stop is requested.

        Returns the last observation seen.
        """
        deadline = (
            time.monotonic() + max_seconds if max_seconds is not None else None
        )
        last_obs: SceneObservation | None = None
        interval = max(0.05, self.config.loop_interval_ms / 1000.0)

        while not self._stop_requested:
            if deadline is not None and time.monotonic() > deadline:
                log.error("engine deadline exceeded")
                break

            frame = self.device.screencap_ndarray()
            obs = self.detector.detect(frame)
            last_obs = obs
            log.debug(f"scene={obs.state}")

            if obs.state == SceneState.UNKNOWN:
                self._unknown_streak += 1
                if self._unknown_streak == 1:
                    self._dump_unknown(frame)
                if self._unknown_streak >= self.config.unknown_scene_limit:
                    log.error(
                        f"UNKNOWN scene streak hit limit ({self._unknown_streak}); aborting"
                    )
                    break
            else:
                self._unknown_streak = 0

            if is_done(obs):
                return obs

            actions: list[Action] = []
            for flow in self.flows:
                actions.extend(flow.decide(obs))

            if not actions:
                # Nothing to do this tick – wait & re-observe.
                time.sleep(interval)
                continue

            for act in actions:
                if not act.precondition(obs):
                    continue
                try:
                    res = act.execute(self.device)
                except Exception as exc:  # noqa: BLE001
                    log.exception(f"action {act!r} raised: {exc!r}")
                    continue
                if not res.ok:
                    log.warning(f"action {act!r} failed: {res.reason}")
                # Slight delay between taps so the UI catches up.
                time.sleep(0.15)
            time.sleep(interval)

        if last_obs is None:  # pragma: no cover – never executed flow
            return SceneObservation(state=SceneState.UNKNOWN, matches={})
        return last_obs

    def run_flows(self, flows: Iterable[_Flow], **kwargs) -> SceneObservation:
        """Convenience: temporarily replace the flow list for one run_until call.

        Used by the scheduler when switching task types.
        """
        prev = self.flows
        self.flows = list(flows)
        try:
            return self.run_until(**kwargs)
        finally:
            self.flows = prev
