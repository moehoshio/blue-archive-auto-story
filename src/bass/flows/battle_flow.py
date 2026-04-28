"""Battle flow: auto/x2 setup, sortie, result handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..actions.macros import enable_auto_and_x2, tap_continue, tap_sortie
from ..vision.state_detector import SceneState

if TYPE_CHECKING:  # pragma: no cover
    from ..actions.base import Action
    from ..config import BattleDefaults
    from ..vision.state_detector import SceneObservation


@dataclass(frozen=True)
class BattleFlowResult:
    done: bool
    victory: bool | None = None
    reason: str = ""


class BattleFlow:
    """One-tick decision logic for battle scenes."""

    def __init__(self, defaults: BattleDefaults) -> None:
        self.defaults = defaults

    def decide(self, observation: SceneObservation) -> list[Action]:
        st = observation.state
        if st == SceneState.BATTLE_READY:
            actions: list[Action] = []
            if self.defaults.enable_auto or self.defaults.enable_x2_speed:
                # Toggle once before sortie. The macro inspects current state and
                # only emits taps for icons that are *off*.
                actions.extend(enable_auto_and_x2(observation))
            actions.extend(tap_sortie(observation))
            return actions

        if st == SceneState.BATTLE_RUNNING:
            # During the auto-battle there's nothing to do – the engine just
            # waits, with overall timeout protection.
            return []

        if st == SceneState.BATTLE_RESULT:
            return tap_continue(observation)

        if st == SceneState.REWARD_POPUP:
            return tap_continue(observation)

        return []

    def is_terminal(self, observation: SceneObservation) -> BattleFlowResult:
        m_v = observation.get("battle/victory")
        m_d = observation.get("battle/defeat")
        if m_v and m_v.found:
            return BattleFlowResult(done=False, victory=True, reason="victory shown")
        if m_d and m_d.found:
            return BattleFlowResult(done=True, victory=False, reason="defeat shown")
        # Battle is "done" once we leave the result screen back into a story or list.
        if observation.state in (SceneState.STORY_PLAYING, SceneState.STORY_LIST, SceneState.HOME):
            return BattleFlowResult(done=True, victory=True, reason=f"left battle into {observation.state}")
        return BattleFlowResult(done=False)
