"""Event flow: navigate from HOME -> event list -> chapter selection.

Navigation here relies on a small set of templates whose presence the user
must capture (see ``bass capture``). The flow is intentionally permissive:
when a required button is missing it simply returns no action and waits, so
the engine's ``unknown_scene_limit`` will eventually trip and surface the
issue in logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..actions.tap import TapTemplateAction
from ..vision.state_detector import SceneState

if TYPE_CHECKING:  # pragma: no cover
    from ..actions.base import Action
    from ..vision.state_detector import SceneObservation


@dataclass
class EventFlowState:
    event_id: str
    chapters: tuple[int, ...]
    chapter_index: int = 0
    completed: list[int] = field(default_factory=list)

    @property
    def current_chapter(self) -> int | None:
        if self.chapter_index >= len(self.chapters):
            return None
        return self.chapters[self.chapter_index]

    def advance(self) -> None:
        if self.current_chapter is not None:
            self.completed.append(self.current_chapter)
        self.chapter_index += 1


class EventFlow:
    """Navigates the event entry. Once the chapter starts (STORY_PLAYING /
    BATTLE_READY), control should be handed back to StoryFlow / BattleFlow."""

    def decide(self, observation: SceneObservation) -> list[Action]:
        st = observation.state
        if st == SceneState.HOME:
            m = observation.get("menu/event_entry")
            if m and m.found:
                return [TapTemplateAction("menu/event_entry", name="OpenEvent")]
        # Story list / event list templates can be tapped to select an entry.
        # Without per-chapter templates we cannot pick a specific row, so we
        # leave that to the user via additional templates if needed.
        return []

    @staticmethod
    def is_in_chapter(observation: SceneObservation) -> bool:
        return observation.state in (
            SceneState.STORY_PLAYING,
            SceneState.BATTLE_READY,
            SceneState.BATTLE_RUNNING,
            SceneState.DIALOG,
        )
