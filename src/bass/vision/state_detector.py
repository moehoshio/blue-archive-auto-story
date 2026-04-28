"""Scene state classification based on which templates are visible.

The detector takes a frame plus a :class:`TemplateMatcher` and returns the most
likely :class:`SceneState`. Each state has a small list of "fingerprint" templates;
the state is selected if *any* of its required fingerprints match (so the engine
can react quickly), but only the most specific state wins when multiple match.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .matcher import MatchResult, TemplateMatcher


class SceneState(str, Enum):
    HOME = "HOME"
    EVENT_LIST = "EVENT_LIST"
    STORY_LIST = "STORY_LIST"
    DIALOG = "DIALOG"
    STORY_PLAYING = "STORY_PLAYING"
    BATTLE_READY = "BATTLE_READY"
    BATTLE_RUNNING = "BATTLE_RUNNING"
    BATTLE_RESULT = "BATTLE_RESULT"
    REWARD_POPUP = "REWARD_POPUP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SceneRule:
    """One state's fingerprint set."""

    state: SceneState
    # Any of these templates being present is sufficient. ("OR")
    any_of: tuple[str, ...] = ()
    # All of these must be present. ("AND")
    all_of: tuple[str, ...] = ()
    # Specificity: higher wins when multiple states match. Battle/result-style
    # screens are "more specific" than e.g. STORY_PLAYING which is broad.
    specificity: int = 0


# Order influences only first-match for ties; specificity is the primary sort.
DEFAULT_RULES: tuple[SceneRule, ...] = (
    SceneRule(SceneState.BATTLE_RESULT, any_of=("battle/victory", "battle/defeat"), specificity=90),
    SceneRule(SceneState.REWARD_POPUP, any_of=("common/confirm", "battle/result_next"), specificity=70),
    SceneRule(
        SceneState.BATTLE_READY,
        any_of=("battle/sortie",),
        specificity=80,
    ),
    SceneRule(
        SceneState.BATTLE_RUNNING,
        any_of=("battle/x1_speed", "battle/x2_speed", "battle/auto_on", "battle/auto_off"),
        specificity=60,
    ),
    SceneRule(
        SceneState.STORY_PLAYING,
        any_of=("story/auto_on", "story/auto_off", "story/menu_button"),
        specificity=50,
    ),
    SceneRule(SceneState.STORY_LIST, any_of=("menu/story_entry",), specificity=40),
    SceneRule(SceneState.EVENT_LIST, any_of=("menu/event_entry",), specificity=40),
    SceneRule(SceneState.HOME, any_of=("menu/home_indicator",), specificity=20),
)


@dataclass(frozen=True)
class SceneObservation:
    state: SceneState
    matches: dict[str, MatchResult]

    def get(self, name: str) -> MatchResult | None:
        return self.matches.get(name)


class StateDetector:
    """Classifies frames into :class:`SceneState`."""

    def __init__(
        self, matcher: TemplateMatcher, rules: tuple[SceneRule, ...] = DEFAULT_RULES
    ) -> None:
        self.matcher = matcher
        self.rules = tuple(sorted(rules, key=lambda r: -r.specificity))
        # Pre-compute the union of templates we need to test.
        self._template_names: tuple[str, ...] = tuple(
            sorted({n for r in rules for n in (*r.any_of, *r.all_of)})
        )

    @property
    def template_names(self) -> tuple[str, ...]:
        return self._template_names

    def detect(self, frame) -> SceneObservation:
        """Match all fingerprint templates against ``frame`` and pick a state."""
        matches: dict[str, MatchResult] = self.matcher.match_any(frame, list(self._template_names))
        return self._classify(matches)

    # Pure function – exposed for unit testing without OpenCV.
    def _classify(self, matches: dict[str, MatchResult]) -> SceneObservation:
        for rule in self.rules:
            any_ok = (not rule.any_of) or any(
                matches.get(n, _NO_MATCH).found for n in rule.any_of
            )
            all_ok = all(matches.get(n, _NO_MATCH).found for n in rule.all_of)
            if any_ok and all_ok and (rule.any_of or rule.all_of):
                return SceneObservation(state=rule.state, matches=matches)
        return SceneObservation(state=SceneState.UNKNOWN, matches=matches)


_NO_MATCH = MatchResult(name="", found=False, score=0.0, center=(0, 0), bbox=(0, 0, 0, 0))
