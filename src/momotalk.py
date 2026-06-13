"""MomoTalk automation.

A separate task from the main story automator (automator.py): reads through every unread
conversation — handling reply options, entering and skipping attached Relationship Stories,
collecting rewards — then switches to the next unread. When no more unread conversations are
reachable in the current list, it closes and reopens MomoTalk to refresh; once the home-screen
badge disappears, the task is done.

Screen flow (observed):
  Conversation → reply option → (typing… → new messages) → pink "Relationship Event /
  Relationship Story" button → "Begin Relationship Story" → story screen (Auto/Menu, reusing
  main-story skip) → "TOUCH TO CONTINUE" reward → back to conversation (may have more) → …
  → no new content.

Detection strategy (template-first, same as main automator; coordinate-based taps only for
elements that can't be reliably templated — conversation list rows, tabs, badge):
  - State / buttons: momotalk_title, momotalk_reward, momotalk_story_begin, momotalk_notice,
    plus the main-story templates story_menu / story_skip / …
  - Pink "Relationship Story" in-conversation button: detected by HSV color (button text
    contains the character's name in small font → template unstable across characters).
  - "Typing… / new message": average pixel diff between two consecutive conversation-panel
    crops; inactivity for idle_switch_ticks → conversation is done.
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Optional, Tuple

import cv2
import numpy as np

from . import notify
from .adb import Adb
from .assets import THRESHOLD_OVERRIDES, load_assets
from .config import Config
from .vision import Match, TemplateMatcher, to_gray

log = logging.getLogger(__name__)


class MomoStop(str, Enum):
    DONE = "no unread left, momotalk finished"
    STUCK = "no progress for too long, manual help needed"
    MANUAL_NETWORK = "reconnect attempts exceeded, manual help needed"
    INTERRUPTED = "interrupted by user"


class MomoTalkAutomator:
    def __init__(self, cfg: Config, adb: Adb):
        self.cfg = cfg
        self.mt = cfg.momotalk
        self.adb = adb
        self.matcher = TemplateMatcher(cfg.matching)
        self.groups = load_assets(cfg.assets_dir)

        self._gray = None
        self._bgr = None             # Current tick's color frame (for pink-button / badge detection)
        self._find_cache: dict = {}
        self._prev_convo: Optional[np.ndarray] = None  # Previous tick's conversation panel (grayscale, for change detection)
        self._idle = 0              # Consecutive ticks with no conversation change and no actionable element
        self._switches = 0          # Row switches since the last progress event
        self._grace = 0             # Loading grace ticks after a transition (entering story / reward)
        self._home_empty = 0        # Consecutive ticks with no unread badge on the home screen (for done confirmation)
        self._reconnect_count = 0   # Consecutive reconnect taps (stops if over the limit)
        self._sx = 1.0              # Actual width / reference width
        self._sy = 1.0

    # ---- Coordinate scaling (reference 1920x1080 → actual screen) ----
    def _pt(self, xy) -> Tuple[int, int]:
        return int(xy[0] * self._sx), int(xy[1] * self._sy)

    def _box(self, roi) -> Tuple[int, int, int, int]:
        x0, y0, x1, y1 = roi
        return (int(x0 * self._sx), int(y0 * self._sy),
                int(x1 * self._sx), int(y1 * self._sy))

    # ---- Template matching (same per-tick cache convention as the main automator) ----
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

    # ---- Tap helpers ----
    def _tap_xy(self, x: int, y: int, label: str) -> None:
        log.info("action: %-22s tap (%d,%d)", label, x, y)
        self.adb.tap(x, y)
        time.sleep(self.mt.tap_delay)

    def _tap(self, m: Match, label: str) -> None:
        log.info("action: %-22s tap (%d,%d) <%s score=%.2f>", label, m.x, m.y, m.file, m.score)
        self.adb.tap(m.x, m.y)
        time.sleep(self.mt.tap_delay)

    def _tap_ref(self, xy, label: str) -> None:
        x, y = self._pt(xy)
        self._tap_xy(x, y, label)

    # ---- Main loop ----
    def run(self) -> MomoStop:
        self.adb.ensure_device()
        notify.enable_windows_ansi()
        bgr = self.adb.screencap()
        h, w = bgr.shape[:2]
        self._sx = w / self.mt.ref_width
        self._sy = h / self.mt.ref_height
        log.info("momotalk started. screen %dx%d (scale %.3f,%.3f). press Ctrl+C to stop.",
                 w, h, self._sx, self._sy)
        # Give an initial grace window so a startup that lands mid-transition doesn't
        # immediately declare done before any screen element appears.
        self._grace = self.mt.grace_ticks
        try:
            while True:
                reason = self._tick()
                if reason is not None:
                    if reason == MomoStop.DONE:
                        notify.manual("momotalk_done")
                    elif reason == MomoStop.STUCK:
                        notify.manual("stuck")
                    log.info("finished: %s", reason.value)
                    return reason
                time.sleep(self.mt.tick_interval)
        except KeyboardInterrupt:
            log.info("interrupt received.")
            return MomoStop.INTERRUPTED

    def _tick(self) -> Optional[MomoStop]:
        self._bgr = self.adb.screencap()
        self._gray = to_gray(self._bgr)
        self._find_cache = {}

        # 0) NOTICE interrupt: network disconnects can occur at any time (same priority as main automator).
        nr = self._handle_notice()
        if nr == "stop":
            notify.manual("network")
            return MomoStop.MANUAL_NETWORK
        if nr is not None:
            self._prev_convo = None  # Notification overlay resets the conversation change baseline
            return None

        # 1) Reward screen (after a relationship story): tap to continue.
        #    Highest priority — this screen overlays everything else.
        if self._present("momotalk_reward"):
            self._tap_ref(self.mt.reward_dismiss_xy, "reward continue")
            return self._progress()

        # 2) Story playback screen (relationship story): reuse main-story skip flow (open menu → skip → confirm).
        if self._in_story():
            self._skip_story_step()
            return self._progress()

        # 3) Relationship story entry: "Begin Relationship Story" panel first (no character name → stable template),
        #    then the in-conversation pink "Relationship Story" button (character name in small text → color detection).
        m = self._find("momotalk_story_begin")
        if m:
            self._tap(m, "begin relationship story")
            return self._progress()
        pink = self._find_story_enter()
        if pink is not None:
            self._tap_xy(pink[0], pink[1], "enter relationship story")
            return self._progress()

        # 4) Inside the MomoTalk conversation popup.
        if self._present("momotalk_title"):
            return self._handle_convo()

        # 5) Not in the conversation popup (closed / on home screen / transitioning): reopen or declare done.
        return self._handle_offscreen()

    def _progress(self) -> None:
        """An action occurred — reset idle/switch counters, change baseline, and arm grace."""
        self._idle = 0
        self._switches = 0
        self._home_empty = 0
        self._prev_convo = None
        self._grace = self.mt.grace_ticks
        return None

    # ---- NOTICE interrupt (reuses main-story templates and network config) ----
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

    # ---- Story skip (reuses main-story templates) ----
    def _in_story(self) -> bool:
        return self._present("story_auto") and (
            self._present("story_menu") or self._present("story_menu_selected"))

    def _skip_story_step(self) -> None:
        m = self._find("story_skip_confirm")
        if m:
            self._tap(m, "skip confirm")
            return
        m = self._find("story_skip")
        if m:
            self._tap(m, "skip")
            return
        if self._present("story_menu_selected"):
            return  # Menu already open; wait for the skip button (re-tapping would close it)
        m = self._find("story_menu")
        if m:
            self._tap(m, "open menu")

    # ---- Conversation handling ----
    def _handle_convo(self) -> Optional[MomoStop]:
        self._home_empty = 0  # MomoTalk is open → definitely not "home screen with no unread"
        # Reply options available → pick the first one (any choice works for affection).
        label = self._find("momotalk_reply")
        if label is not None:
            dx, dy = self.mt.reply_label_offset
            x = label.x + int(dx * self._sx)
            y = label.y + int(dy * self._sy)
            self._tap_xy(x, y, "reply option")
            return self._progress()

        # No actionable element: check whether the conversation panel is changing
        # (other party typing / new messages arriving). Panel static for idle_switch_ticks → switch.
        # The transition grace window is only used by _handle_offscreen (story/reward loading gaps);
        # it does not extend the conversation idle wait here.
        if self._convo_changed():
            self._idle = 0
            return None  # New content arriving — wait for it to settle
        self._idle += 1
        if self._idle < self.mt.idle_switch_ticks:
            return None

        # Current conversation has no new content → switch to another unread row
        # (rows 1, 2, …, visible_rows-1; row 0 is the current/already-processed conversation).
        # After exhausting all reachable rows, close and reopen to refresh — never wrap back to row 0.
        self._idle = 0
        self._switches += 1
        last_row = min(self.mt.max_switches, self.mt.visible_rows - 1)
        if self._switches > last_row:
            # Exhausted all visible rows with no progress → close and reopen to refresh.
            log.info("no progress after %d switches, reopening momotalk.", self._switches - 1)
            self._switches = 0
            self._tap_ref(self.mt.close_xy, "close (refresh)")
            self._grace = self.mt.grace_ticks
            return None
        self._switch_conversation()
        return None

    def _switch_conversation(self) -> None:
        """Tap the _switches-th row (1-based) in the unread list (row 0 is the current conversation)."""
        idx = self._switches
        x = self.mt.first_row_xy[0]
        y = self.mt.first_row_xy[1] + idx * self.mt.row_height
        self._tap_ref((x, y), f"switch unread (row {idx})")
        self._prev_convo = None  # New conversation — reset the change detection baseline
        self._grace = self.mt.grace_ticks

    def _find_story_enter(self) -> Optional[Tuple[int, int]]:
        """Detect the pink "To X's Relationship Story" button in the conversation area by color.
        Returns the tap center or None. Color detection is character-agnostic; small-font template
        matching is unreliable across characters."""
        if self._bgr is None:
            return None
        x0, y0, x1, y1 = self._box(self.mt.story_enter_roi)
        patch = self._bgr[y0:y1, x0:x1]
        if patch.size == 0:
            return None
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, tuple(self.mt.story_enter_hsv_lo), tuple(self.mt.story_enter_hsv_hi))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_w = int(self.mt.story_enter_min_w * self._sx)
        min_h = int(self.mt.story_enter_min_h * self._sy)
        max_h = int(self.mt.story_enter_max_h * self._sy)
        best = None
        for c in cnts:
            bx, by, bw, bh = cv2.boundingRect(c)
            if bw < min_w or bh < min_h or bh > max_h:
                continue
            if best is None or bw > best[2]:
                best = (bx, by, bw, bh)
        if best is None:
            return None
        bx, by, bw, bh = best
        return x0 + bx + bw // 2, y0 + by + bh // 2

    def _convo_changed(self) -> bool:
        """Returns True if the conversation panel changed noticeably since the last tick
        (other party typing / new message arrived)."""
        x0, y0, x1, y1 = self._box(self.mt.convo_roi)
        cur = self._gray[y0:y1, x0:x1]
        prev = self._prev_convo
        self._prev_convo = cur
        if prev is None or prev.shape != cur.shape:
            return True  # First tick or after a conversation switch: treat as changed, wait one tick
        diff = float(cv2.absdiff(cur, prev).mean())
        return diff > self.mt.diff_thresh

    # ---- Off-screen: reopen or declare done ----
    def _handle_offscreen(self) -> Optional[MomoStop]:
        # Use the Notice (speaker) icon as the home-screen anchor — its shape is fixed,
        # unlike the MomoTalk badge which changes number and has a variable lobby background.
        # Icon absent → transition / loading; wait out the grace window before declaring stuck.
        notice = self._find("momotalk_notice")
        if notice is None:
            self._home_empty = 0
            if self._grace > 0:
                self._grace -= 1
                return None
            self._idle += 1
            if self._idle >= self.mt.idle_switch_ticks + self.mt.max_switches + 5:
                return MomoStop.STUCK
            return None
        # On the home screen: MomoTalk entry = notice center + offset.
        # If the unread badge is present → still has unread, reopen to refresh.
        ox, oy = self.mt.notice_home_offset
        mx = notice.x + int(ox * self._sx)
        my = notice.y + int(oy * self._sy)
        if self._home_has_unread(mx, my):
            self._home_empty = 0
            self._reopen(mx, my)
            return None
        # No badge: could be genuinely done, or could be a brief gap right after a story → reward
        # transition (MomoTalk closed, notice visible, but reward screen not yet appeared).
        # Two guards prevent a false "done": (1) grace window suppresses the check; (2) even after
        # grace, require done_confirm_ticks consecutive ticks without a badge — the transition gap
        # is only a few ticks, after which MomoTalk reopens and _handle_convo resets _home_empty.
        if self._grace > 0:
            self._grace -= 1
            return None
        self._home_empty += 1
        if self._home_empty >= self.mt.done_confirm_ticks:
            return MomoStop.DONE
        return None

    def _reopen(self, home_x: int, home_y: int) -> None:
        """Reopen MomoTalk and navigate to the top of the unread list:
        tap home entry → unread tab → topmost conversation row.
        Entry coordinates are derived from the notice anchor (stable across lobby changes)."""
        self._tap_xy(home_x, home_y, "reopen momotalk")
        time.sleep(self.mt.tap_delay)
        self._tap_ref(self.mt.unread_tab_xy, "unread tab")
        self._tap_ref(self.mt.first_row_xy, "open top unread")
        self._idle = 0
        self._switches = 0
        self._prev_convo = None
        self._grace = self.mt.grace_ticks

    def _home_has_unread(self, home_x: int, home_y: int) -> bool:
        """Check whether the MomoTalk entry on the home screen has a red unread badge.
        The badge ROI is relative to the entry center (moves with the notice anchor),
        and is detected by saturated red pixels in HSV."""
        dx0, dy0, dx1, dy1 = self.mt.home_badge_rel
        x0 = home_x + int(dx0 * self._sx); y0 = home_y + int(dy0 * self._sy)
        x1 = home_x + int(dx1 * self._sx); y1 = home_y + int(dy1 * self._sy)
        patch = self._bgr[y0:y1, x0:x1]
        if patch.size == 0:
            return False
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 120, 120), (12, 255, 255)) | \
            cv2.inRange(hsv, (168, 120, 120), (180, 255, 255))
        return int(cv2.countNonZero(mask)) > patch.shape[0] * patch.shape[1] * 0.08
