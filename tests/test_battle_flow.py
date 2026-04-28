"""Tests for flows.battle_flow decision logic.

We feed BattleFlow synthetic SceneObservations (no OpenCV needed) and assert it
emits the expected Action sequence.
"""

from __future__ import annotations

from bass.actions.tap import TapTemplateAction
from bass.config import BattleDefaults
from bass.flows.battle_flow import BattleFlow
from bass.vision.matcher import MatchResult
from bass.vision.state_detector import SceneObservation, SceneState


def _hit(name: str) -> MatchResult:
    return MatchResult(name=name, found=True, score=0.99, center=(100, 100), bbox=(0, 0, 1, 1))


def _miss(name: str) -> MatchResult:
    return MatchResult(name=name, found=False, score=0.0, center=(0, 0), bbox=(0, 0, 0, 0))


def _obs(state: SceneState, **matches: MatchResult) -> SceneObservation:
    return SceneObservation(state=state, matches=matches)


# ---------------------------------------------------------------------------


def test_battle_ready_enables_auto_x2_then_sorties() -> None:
    flow = BattleFlow(BattleDefaults())
    obs = _obs(
        SceneState.BATTLE_READY,
        **{
            "battle/sortie": _hit("battle/sortie"),
            "battle/auto_off": _hit("battle/auto_off"),
            "battle/x1_speed": _hit("battle/x1_speed"),
        },
    )
    actions = flow.decide(obs)
    names = [a.template_name for a in actions if isinstance(a, TapTemplateAction)]
    # auto/x2 are toggled before sortie.
    assert names == ["battle/auto_off", "battle/x1_speed", "battle/sortie"]


def test_battle_ready_skips_toggle_when_already_on() -> None:
    flow = BattleFlow(BattleDefaults())
    obs = _obs(
        SceneState.BATTLE_READY,
        **{
            "battle/sortie": _hit("battle/sortie"),
            # auto_on (not _off), x2_speed (not x1) => already configured.
            "battle/auto_off": _miss("battle/auto_off"),
            "battle/x1_speed": _miss("battle/x1_speed"),
        },
    )
    actions = flow.decide(obs)
    names = [a.template_name for a in actions if isinstance(a, TapTemplateAction)]
    assert names == ["battle/sortie"]


def test_battle_ready_respects_disabled_defaults() -> None:
    flow = BattleFlow(BattleDefaults(enable_auto=False, enable_x2_speed=False))
    obs = _obs(
        SceneState.BATTLE_READY,
        **{
            "battle/sortie": _hit("battle/sortie"),
            "battle/auto_off": _hit("battle/auto_off"),
            "battle/x1_speed": _hit("battle/x1_speed"),
        },
    )
    actions = flow.decide(obs)
    names = [a.template_name for a in actions if isinstance(a, TapTemplateAction)]
    assert names == ["battle/sortie"]


def test_battle_running_is_no_op() -> None:
    flow = BattleFlow(BattleDefaults())
    obs = _obs(SceneState.BATTLE_RUNNING)
    assert flow.decide(obs) == []


def test_battle_result_taps_continue() -> None:
    flow = BattleFlow(BattleDefaults())
    obs = _obs(
        SceneState.BATTLE_RESULT,
        **{"battle/result_next": _hit("battle/result_next")},
    )
    actions = flow.decide(obs)
    assert len(actions) == 1
    assert isinstance(actions[0], TapTemplateAction)
    assert actions[0].template_name == "battle/result_next"


def test_is_terminal_reports_victory_and_defeat() -> None:
    flow = BattleFlow(BattleDefaults())
    obs_v = _obs(SceneState.BATTLE_RESULT, **{"battle/victory": _hit("battle/victory")})
    res = flow.is_terminal(obs_v)
    assert res.victory is True

    obs_d = _obs(SceneState.BATTLE_RESULT, **{"battle/defeat": _hit("battle/defeat")})
    res = flow.is_terminal(obs_d)
    assert res.done is True
    assert res.victory is False


def test_is_terminal_done_when_back_to_story_or_home() -> None:
    flow = BattleFlow(BattleDefaults())
    for st in (SceneState.STORY_LIST, SceneState.HOME, SceneState.STORY_PLAYING):
        res = flow.is_terminal(_obs(st))
        assert res.done is True
        assert res.victory is True
