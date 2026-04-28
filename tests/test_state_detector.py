"""Tests for vision.state_detector classification logic.

These tests poke ``StateDetector._classify`` directly so they don't depend on
OpenCV being installed (only the matcher's match dict is needed).
"""

from __future__ import annotations

from bass.vision.matcher import MatchResult
from bass.vision.state_detector import (
    DEFAULT_RULES,
    SceneRule,
    SceneState,
    StateDetector,
)


class _DummyMatcher:
    """No-op matcher; we never call .match because we inject the matches dict."""

    def match_any(self, frame, names):  # pragma: no cover – not used here
        raise AssertionError("not expected to be called in classifier-only tests")


def _hit(name: str, score: float = 0.95) -> MatchResult:
    return MatchResult(name=name, found=True, score=score, center=(0, 0), bbox=(0, 0, 1, 1))


def _miss(name: str) -> MatchResult:
    return MatchResult(name=name, found=False, score=0.0, center=(0, 0), bbox=(0, 0, 0, 0))


def _detector() -> StateDetector:
    return StateDetector(_DummyMatcher())  # uses DEFAULT_RULES


def test_default_rules_cover_required_states() -> None:
    states = {r.state for r in DEFAULT_RULES}
    for required in (
        SceneState.HOME,
        SceneState.STORY_PLAYING,
        SceneState.BATTLE_READY,
        SceneState.BATTLE_RESULT,
        SceneState.REWARD_POPUP,
    ):
        assert required in states


def test_classifier_detects_home() -> None:
    obs = _detector()._classify({"menu/home_indicator": _hit("menu/home_indicator")})
    assert obs.state == SceneState.HOME


def test_classifier_detects_story_playing() -> None:
    obs = _detector()._classify({"story/auto_off": _hit("story/auto_off")})
    assert obs.state == SceneState.STORY_PLAYING


def test_classifier_detects_battle_ready() -> None:
    obs = _detector()._classify({"battle/sortie": _hit("battle/sortie")})
    assert obs.state == SceneState.BATTLE_READY


def test_classifier_detects_battle_result_over_reward() -> None:
    """Both rules could fire – BATTLE_RESULT has higher specificity."""
    matches = {
        "battle/victory": _hit("battle/victory"),
        "common/confirm": _hit("common/confirm"),
    }
    obs = _detector()._classify(matches)
    assert obs.state == SceneState.BATTLE_RESULT


def test_classifier_unknown_when_nothing_matches() -> None:
    obs = _detector()._classify(
        {n: _miss(n) for n in ("menu/home_indicator", "battle/sortie", "story/auto_on")}
    )
    assert obs.state == SceneState.UNKNOWN


def test_classifier_specificity_overrides_order() -> None:
    """Even if a low-spec rule comes first in the input, the high-spec rule wins."""
    rules = (
        SceneRule(SceneState.HOME, any_of=("menu/home_indicator",), specificity=10),
        SceneRule(SceneState.BATTLE_READY, any_of=("battle/sortie",), specificity=80),
    )
    detector = StateDetector(_DummyMatcher(), rules=rules)
    matches = {
        "menu/home_indicator": _hit("menu/home_indicator"),
        "battle/sortie": _hit("battle/sortie"),
    }
    obs = detector._classify(matches)
    assert obs.state == SceneState.BATTLE_READY


def test_template_names_are_unique_and_cover_rules() -> None:
    detector = _detector()
    names = detector.template_names
    assert len(names) == len(set(names))
    for r in DEFAULT_RULES:
        for n in (*r.any_of, *r.all_of):
            assert n in names
