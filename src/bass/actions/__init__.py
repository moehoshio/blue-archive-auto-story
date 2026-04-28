"""Action sub-package.

An :class:`~bass.actions.base.Action` represents a single, idempotent step that
the engine can execute when its precondition is satisfied. Actions encapsulate:

    * a name (for logs / debugging)
    * a precondition (does this action apply to the current scene?)
    * an execute(device) implementation
    * an optional postcondition (verifies the action took effect)

High-level macros that combine multiple actions live in :mod:`.macros`.
"""

from .base import Action, ActionResult
from .macros import (
    enable_auto_and_x2,
    open_battle_settings,
    tap_continue,
    tap_skip_dialog,
    tap_sortie,
)
from .swipe import SwipeAction
from .tap import TapAction, TapTemplateAction

__all__ = [
    "Action",
    "ActionResult",
    "TapAction",
    "TapTemplateAction",
    "SwipeAction",
    "tap_skip_dialog",
    "tap_continue",
    "tap_sortie",
    "open_battle_settings",
    "enable_auto_and_x2",
]
