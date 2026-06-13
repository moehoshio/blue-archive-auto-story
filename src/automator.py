"""Flow-state machine that drives the auto-story.

States (see user's spec):
  LIST      story list, not entered. Always has book + enter.
  STORY     story playing. Top-right has auto + menu.
  MOBILIZE  pre-combat formation screen. Has the mobilize button.
  COMBAT    in battle. Has auto (on/off) + speed (1-3) controls.
  RESULT    battle result. Always has the analyze icon; the confirm button differs
            for win (combat_completed_confirm, bottom-right) vs lose
            (combat_failure_confirm, bottom-center, needs a 2nd tap for its tips).
  NOTICE    is handled as a per-tick interrupt (network failure can occur during any
            flow transition), not as a sticky state.

General flow:
  LIST -> STORY -> (combat? MOBILIZE -> COMBAT -> RESULT ->) STORY -> ... -> chapter end.
  With "auto continuous play" + "auto next chapter" ON, the game advances episodes /
  chapters by itself; this tool mainly skips dialogue, runs combat, turns pages, and
  ends the task when the whole chapter is cleared.

Detection is CNF + sticky: a state is confirmed only when every clause has >=1 hit
(clauses AND'd, members OR'd) -> needs several required elements at once, so a single
false hit can't flip the state. State only changes when *another* state is positively
detected; transient blank frames (loading / animations) keep the current state.

"Stuck" is only declared when *no* state can be confirmed for a long time. While a state
is confirmed (e.g. a 1-2 min auto-battle still showing auto/speed) the idle counter stays
at zero, so long legitimate waits never trigger a false stuck.
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import List, Optional, Union

from . import notify
from .adb import Adb
from .assets import THRESHOLD_OVERRIDES, load_assets
from .config import Config
from .vision import Match, Template, TemplateMatcher, to_gray

log = logging.getLogger(__name__)


class StopReason(str, Enum):
    COMPLETED = "chapter complete, task finished"
    STUCK = "no actionable element for too long, manual help needed"
    MANUAL_NETWORK = "reconnect attempts exceeded, manual help needed"
    INTERRUPTED = "interrupted by user"


class State(str, Enum):
    LIST = "LIST"
    STORY = "STORY"
    MOBILIZE = "MOBILIZE"
    COMBAT = "COMBAT"
    RESULT = "RESULT"


# CNF detection per state: AND across clauses, OR within a clause. Ordered specific
# -> general; the first fully-satisfied state wins.
STATE_DETECT = {
    # Battle result: the analyze icon is always present; a confirm (win or lose) too.
    State.RESULT: [
        ["combat_completed_icon", "combat_completed", "combat_failure"],
    ],
    # In battle: an AUTO control AND a speed indicator must BOTH be present. Requiring
    # both is essential — an auto-like element alone shows up in too many non-combat
    # scenes, so auto-or-speed would false-trigger COMBAT.
    State.COMBAT: [
        ["combat_auto_off", "combat_auto_on"],
        ["combat_speed_1", "combat_speed_2", "combat_speed_3"],
    ],
    # Pre-combat formation screen.
    State.MOBILIZE: [
        ["combat_mobilize"],
    ],
    # Story playback: auto AND menu in the top-right.
    State.STORY: [
        ["story_auto"],
        ["story_menu", "story_menu_selected"],
    ],
    # Story list: a book marker AND an enter button.
    State.LIST: [
        ["book_done", "book_undone"],
        ["story_enter", "story_enter_with_combat", "story_enter_episode"],
    ],
}

# Run a full all-states relocate scan after this many consecutive ticks with no current-flow element
# (keeps the expensive all-states scan rare rather than every tick).
RELOCATE_INTERVAL = 4


class StoryAutomator:
    def __init__(self, cfg: Config, adb: Adb):
        self.cfg = cfg
        self.adb = adb
        self.matcher = TemplateMatcher(cfg.matching)
        self.groups = load_assets(cfg.assets_dir)

        self._gray = None
        self._find_cache: dict = {}        # per-tick match cache (same frame/group reused)
        self._state: Optional[State] = None  # None until first located
        self._reconnect_count = 0
        self._lost = 0                     # consecutive ticks with no action and no state
        self._grace = 0                    # post-transition exemption: blank ticks don't count while >0
        self._entered = False              # have we entered any story yet
        self._fail_tip_at = None           # pending 2nd tap for a failure tips popup
        self._failure_ticks = 0            # >0 shortly after a battle loss (refines stuck msg)
        self._auto_taps = 0                # enable-auto taps this battle (cap: auto may be locked)
        self._speed_done = False           # speed already set this battle (set once, no oscillation)
        self._mobilize_taps = 0            # mobilize taps this screen (cap: empty team can't start)

    # ---- match helpers ----
    def _find(self, group: str, threshold: Optional[float] = None) -> Optional[Match]:
        key = (group, threshold)
        if key in self._find_cache:
            return self._find_cache[key]
        tpls = self.groups.get(group)
        if not tpls:
            self._find_cache[key] = None
            return None
        thr = threshold if threshold is not None else THRESHOLD_OVERRIDES.get(group)
        m = self.matcher.find(self._gray, tpls, thr)
        self._find_cache[key] = m
        return m

    def _present(self, group: str, threshold: Optional[float] = None) -> bool:
        return self._find(group, threshold) is not None

    def _any(self, groups: List[str]) -> bool:
        return any(self._present(g) for g in groups)

    def _satisfies(self, clauses: List[List[str]]) -> bool:
        return all(self._any(c) for c in clauses)

    def _enter_templates(self) -> List[Template]:
        out: List[Template] = []
        for g in ("story_enter", "story_enter_with_combat"):
            out.extend(self.groups.get(g, []))
        return out

    def _tap(self, m: Match, label: str) -> None:
        log.info("action: %-20s tap (%d,%d) <%s score=%.2f scale=%.2f>",
                 label, m.x, m.y, m.file, m.score, m.scale)
        self.adb.tap(m.x, m.y)
        time.sleep(self.cfg.loop.tap_delay)

    # ---- main loop ----
    def run(self) -> StopReason:
        self.adb.ensure_device()
        notify.enable_windows_ansi()
        log.info("auto-story started. press Ctrl+C to stop.")
        try:
            while True:
                reason = self._tick()
                if reason is not None:
                    log.info("finished: %s", reason.value)
                    return reason
                time.sleep(self.cfg.loop.tick_interval)
        except KeyboardInterrupt:
            log.info("interrupt received.")
            return StopReason.INTERRUPTED

    def _tick(self) -> Optional[StopReason]:
        self._gray = to_gray(self.adb.screencap())
        self._find_cache = {}
        if self._failure_ticks > 0:
            self._failure_ticks -= 1

        # 1) NOTICE interrupt: network issues can appear during any transition.
        nr = self._handle_notice()
        if nr == "stop":
            notify.manual("network")
            return StopReason.MANUAL_NETWORK
        if nr is not None:
            self._mark_progress()
            return None

        # 2) make sure we have a current state.
        if self._state is None:
            self._locate()

        # 3) run the current state's handler. Handlers act on their own elements AND
        #    follow the natural next-step gateways (story->mobilize->combat->result->...),
        #    so ordinary flow never needs the costly all-states scan.
        if self._state is not None:
            r = self._dispatch()
            if isinstance(r, StopReason):
                return r
            if r == "acted":
                self._mark_progress()  # an action/transition -> expect a loading gap next
                return None

        # 4) current state still confirmed? then we simply know where we are (loading /
        #    battle in progress) -> not stuck.
        if self._state is not None and self._satisfies(STATE_DETECT[self._state]):
            self._lost = 0
            return None

        # 5) nothing recognizable. During the post-transition grace window, blank frames
        #    are exempt (expected loading) and cost nothing extra -> we do NOT run the
        #    expensive all-states relocate here. Detection speed is unchanged; we just
        #    keep screencapping and let the current handler act when its elements appear.
        if self._grace > 0:
            self._grace -= 1
            return None
        self._lost += 1
        # 6) current-flow elements absent for a while -> periodically re-evaluate which
        #    state we are actually in (the user's "re-detect when nothing shows up for too
        #    long"). Not every tick -> keeps the costly all-states scan rare.
        if self._lost % RELOCATE_INTERVAL == 0:
            prev = self._state
            self._locate()
            if self._state is not prev:
                return None  # _locate() reset lost/grace on the switch
        if self._lost >= self.cfg.loop.idle_ticks_to_end:
            notify.manual("combat_lost_home" if self._failure_ticks > 0 else "stuck")
            return StopReason.STUCK
        return None

    def _mark_progress(self) -> None:
        """Reset the stuck tally and (re)arm the transition grace window."""
        self._lost = 0
        self._grace = self.cfg.loop.transition_grace_ticks

    def _switch(self, state: State) -> None:
        """Transition to a new state (from a handler gateway or relocate). Resets the
        per-battle caps and arms the grace window."""
        if state is not self._state:
            log.info("state: %s -> %s",
                     self._state.value if self._state else "unknown", state.value)
            if state == State.COMBAT:
                self._auto_taps = 0
                self._speed_done = False
            if state == State.MOBILIZE:
                self._mobilize_taps = 0
            self._state = state
        self._mark_progress()

    def _locate(self) -> None:
        """Full all-states scan (fallback re-evaluation). Sets self._state to the first
        CNF-satisfied state; if none match, keeps the current state (sticky)."""
        for state, clauses in STATE_DETECT.items():
            if self._satisfies(clauses):
                self._switch(state)
                return

    def _dispatch(self) -> Union[StopReason, str, None]:
        if self._state == State.RESULT:
            return self._handle_result()
        if self._state == State.COMBAT:
            return self._handle_combat()
        if self._state == State.MOBILIZE:
            return self._handle_mobilize()
        if self._state == State.STORY:
            return self._handle_story()
        if self._state == State.LIST:
            return self._handle_list()
        return None

    # ---- NOTICE (interrupt) ----
    def _handle_notice(self) -> Optional[str]:
        m = self._find("network_reconnect")
        if m:
            self._reconnect_count += 1
            if self._reconnect_count > self.cfg.network.max_reconnect:
                log.error("reconnect failed after %d attempts.", self._reconnect_count)
                return "stop"
            self._tap(m, f"reconnect ({self._reconnect_count})")
            return "acted"
        if self._present("network_notice"):
            log.warning("network notice detected, waiting for recovery...")
            return "wait"
        self._reconnect_count = 0
        return None

    # ---- state handlers ----
    def _handle_list(self) -> Union[StopReason, str]:
        # episode-info popup we opened -> confirm entry.
        m = self._find("story_enter_episode")
        if m:
            self._entered = True
            self._tap(m, "enter episode")
            return "acted"
        # advance to the next cleared section.
        m = self._find("next_page")
        if m:
            self._tap(m, "next page")
            return "acted"
        # everything cleared and no next page -> chapter done (manual next chapter).
        if self._present("story_cleared"):
            notify.manual("chapter_done")
            return StopReason.COMPLETED
        # gateway: we've entered a story (list -> story).
        if self._satisfies(STATE_DETECT[State.STORY]):
            self._switch(State.STORY)
            return "acted"
        # otherwise enter the topmost unlocked (= latest uncompleted) stage.
        target = self._pick_enter()
        if target:
            self._tap(target, "enter stage")
            return "acted"
        return "wait"

    def _pick_enter(self) -> Optional[Match]:
        """Topmost enter button that is not locked. A locked stage shows a lock icon in
        the same row; pick the highest enter with no lock nearby (= newest unfinished)."""
        enters = self.matcher.find_all(self._gray, self._enter_templates())
        if not enters:
            return None
        locks = self.matcher.find_all(self._gray, self.groups.get("lock", []))
        enters.sort(key=lambda m: m.y)  # topmost first
        for e in enters:
            if not any(abs(l.y - e.y) < e.h for l in locks):
                return e
        return enters[0]  # all look locked; fall back to topmost

    def _handle_story(self) -> str:
        m = self._find("story_skip_confirm")
        if m:
            self._tap(m, "skip confirm")
            return "acted"
        m = self._find("story_skip")
        if m:
            self._tap(m, "skip")
            return "acted"
        if self._present("story_menu_selected"):
            return "wait"  # menu open, wait for skip; re-tapping would close it
        m = self._find("story_menu")
        if m:
            self._tap(m, "open menu")
            return "acted"
        # gateway: story -> combat (the mobilize/pre-combat screen appeared).
        if self._present("combat_mobilize"):
            self._switch(State.MOBILIZE)
            return "acted"
        return "wait"  # nothing to do; let auto-play advance

    def _handle_mobilize(self) -> Union[StopReason, str]:
        m = self._find("combat_mobilize")
        if m:
            # If the team is empty (or mobilize otherwise can't start), the button stays
            # and tapping does nothing. Cap the taps and alert instead of looping forever.
            if self._mobilize_taps >= 5:
                notify.manual("mobilize_stall")
                return StopReason.STUCK
            self._mobilize_taps += 1
            self._tap(m, "mobilize")
            return "acted"
        # gateway: mobilize -> combat (battle UI with auto + speed appeared).
        if self._satisfies(STATE_DETECT[State.COMBAT]):
            self._switch(State.COMBAT)
            return "acted"
        return "wait"  # loading into battle

    def _handle_combat(self) -> str:
        off = self._auto_off_button()
        if off is not None and self._auto_taps < 3:
            # cap re-taps: in some raids AUTO is locked and never flips to on.
            self._auto_taps += 1
            self._tap(off, "enable auto")
            return "acted"
        if self._set_speed():
            return "acted"
        # gateway: combat -> result (analyze icon / confirm appeared).
        if self._satisfies(STATE_DETECT[State.RESULT]):
            self._switch(State.RESULT)
            return "acted"
        return "wait"  # battle running on auto

    def _auto_off_button(self) -> Optional[Match]:
        """The AUTO button matches both on/off templates in grayscale (same 'AUTO' text);
        decide by score. Return the off-match only when it's the stronger one."""
        off = self._find("combat_auto_off")
        if off is None:
            return None
        on = self._find("combat_auto_on")
        return off if (on is None or off.score > on.score) else None

    def _set_speed(self) -> bool:
        """Set battle speed to the desired multiplier, once per battle. The speed button
        shows the current level (1/2/3) and tapping cycles up (1->2->3). Detect the
        current level and tap exactly (desired - current) times in one go.

        Done at most once per battle (`_speed_done`): if the speed control is ambiguous
        / not a standard 1-2-3 indicator (e.g. some event stages), we still only try
        once instead of oscillating or spamming."""
        desired = self.cfg.combat.desired_speed
        if desired <= 1 or self._speed_done:
            return False
        if self._present(f"combat_speed_{desired}"):
            self._speed_done = True       # already at the target speed
            return False
        # find the current level (1 or 2) and tap up to the target.
        for cur in (1, 2):
            btn = self._find(f"combat_speed_{cur}")
            if btn is None:
                continue
            taps = desired - cur
            if taps <= 0:
                self._speed_done = True
                return False
            for _ in range(taps):
                self._tap(btn, f"speed {cur}->{desired}")
            self._speed_done = True
            return True
        return False  # speed control not recognized this tick; retry next tick

    def _handle_result(self) -> str:
        m = self._find("combat_completed")
        if m:
            self._tap(m, "result confirm (win)")
            return "acted"
        m = self._find("combat_failure")
        if m:
            self._tap(m, "result confirm (lose)")
            self._fail_tip_at = (m.x, m.y)   # the lose path pops a tips needing a 2nd tap
            self._failure_ticks = 15
            return "acted"
        if self._fail_tip_at is not None:
            x, y = self._fail_tip_at
            self._fail_tip_at = None
            log.info("action: %-20s tap (%d,%d) <failure tips 2nd click>", "result tips", x, y)
            self.adb.tap(x, y)
            time.sleep(self.cfg.loop.tap_delay)
            return "acted"
        # gateway: result -> back to story (scripted continue) or list (returned to list).
        if self._satisfies(STATE_DETECT[State.STORY]):
            self._switch(State.STORY)
            return "acted"
        if self._satisfies(STATE_DETECT[State.LIST]):
            self._switch(State.LIST)
            return "acted"
        return "wait"
