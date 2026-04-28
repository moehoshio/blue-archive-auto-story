"""High-level macros built on simple Actions.

These functions are *generators* of Action sequences. They are intentionally
stateless – they take a :class:`SceneObservation` so they know where templates
were matched and produce a list of actions to run *now*.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .tap import TapAction, TapTemplateAction

if TYPE_CHECKING:  # pragma: no cover
    from ..vision.state_detector import SceneObservation


# ---------------------------------------------------------------------------
# Story
# ---------------------------------------------------------------------------


def tap_skip_dialog(observation: SceneObservation, *, advance_xy: tuple[int, int]) -> list:
    """Advance one frame of dialogue.

    Strategy:
      * If a "next/continue" template is visible, tap that.
      * Otherwise tap a known-safe central point provided by the caller
        (typically near the bottom-center of the dialog box).
    """
    actions: list = []
    for tmpl in ("common/next", "common/confirm"):
        m = observation.get(tmpl)
        if m and m.found:
            actions.append(TapTemplateAction(tmpl, name=f"DialogAdvance:{tmpl}"))
            return actions
    actions.append(TapAction(*advance_xy, name="DialogAdvance:safe-center"))
    return actions


def tap_continue(observation: SceneObservation) -> list:
    """Generic 'continue / confirm / next' tap when wrapping up a screen."""
    for tmpl in ("battle/result_next", "common/next", "common/confirm"):
        m = observation.get(tmpl)
        if m and m.found:
            return [TapTemplateAction(tmpl, name=f"Continue:{tmpl}")]
    return []


# ---------------------------------------------------------------------------
# Battle
# ---------------------------------------------------------------------------


def tap_sortie(observation: SceneObservation) -> list:
    m = observation.get("battle/sortie")
    if m and m.found:
        return [TapTemplateAction("battle/sortie", name="Sortie")]
    return []


def open_battle_settings(observation: SceneObservation) -> list:  # noqa: ARG001
    """No-op placeholder – BA's battle UI exposes auto/x2 directly on the HUD,
    so this is here mainly as an extension point if a future UI requires
    opening a settings drawer first."""
    return []


def enable_auto_and_x2(observation: SceneObservation) -> list:
    """Toggle AUTO on and speed to x2 if they aren't already.

    The icons are differentiated by template name (e.g. ``battle/auto_on`` vs.
    ``battle/auto_off``). When the *off* variant is matched we tap to flip it.
    """
    actions: list = []
    auto_off = observation.get("battle/auto_off")
    if auto_off and auto_off.found:
        actions.append(TapTemplateAction("battle/auto_off", name="EnableAuto"))
    x1 = observation.get("battle/x1_speed")
    if x1 and x1.found:
        actions.append(TapTemplateAction("battle/x1_speed", name="EnableX2Speed"))
    return actions
