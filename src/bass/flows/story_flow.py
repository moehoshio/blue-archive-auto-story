"""Story flow: auto-advance dialogue and choices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..actions.macros import tap_continue, tap_skip_dialog
from ..vision.state_detector import SceneState

if TYPE_CHECKING:  # pragma: no cover
    from ..actions.base import Action
    from ..config import StoryDefaults
    from ..vision.state_detector import SceneObservation


@dataclass(frozen=True)
class StoryFlowResult:
    done: bool
    reason: str = ""


class StoryFlow:
    """Decides what to do given an observation while we're playing a story.

    The flow is *one-tick* – :meth:`decide` returns the actions to run for the
    current observation. The engine drives the loop.
    """

    def __init__(
        self,
        defaults: StoryDefaults,
        *,
        advance_xy: tuple[int, int] = (640, 600),
        first_choice_xy: tuple[int, int] = (640, 360),
    ) -> None:
        self.defaults = defaults
        self.advance_xy = advance_xy
        self.first_choice_xy = first_choice_xy

    def decide(self, observation: SceneObservation) -> list[Action]:
        from ..actions.tap import TapAction

        st = observation.state
        if st == SceneState.STORY_PLAYING:
            # If a choice marker is visible, pick the first option.
            choice = observation.get("story/choice_marker")
            if choice and choice.found and self.defaults.pick_first_choice:
                return [TapAction(*self.first_choice_xy, name="StoryChoice:first")]
            return tap_skip_dialog(observation, advance_xy=self.advance_xy)
        if st == SceneState.REWARD_POPUP:
            return tap_continue(observation) or [
                TapAction(*self.advance_xy, name="RewardDismiss")
            ]
        return []

    def is_terminal(self, observation: SceneObservation) -> StoryFlowResult:
        if observation.state in (SceneState.STORY_LIST, SceneState.HOME):
            return StoryFlowResult(done=True, reason=f"reached {observation.state}")
        return StoryFlowResult(done=False)
