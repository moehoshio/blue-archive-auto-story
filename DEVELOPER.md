# Developer Notes

This document covers architecture, internals, and conventions for contributors.

---

## Architecture Overview

```
main.py
  └─ StoryAutomator (automator.py)   main/event story — reactive state machine
  └─ MomoTalkAutomator (momotalk.py) MomoTalk — sequential task runner
       └─ Adb (adb.py)               screencap + tap via ADB
       └─ TemplateMatcher (vision.py) multi-scale OpenCV template matching
       └─ load_assets (assets.py)     template registry → Template objects
       └─ Config (config.py)          typed config loaded from config.yaml
```

Both automators share the same `Adb`, `TemplateMatcher`, and asset groups. Each runs its own tick loop.

---

## State Machine (automator.py)

The main automator is a **reactive state machine** — it takes one screenshot per tick and dispatches based on the current state. States:

```
LIST → STORY → [MOBILIZE → COMBAT → RESULT →] STORY → ... → chapter done
```

State detection uses **Conjunctive Normal Form (CNF)**: a state is confirmed only when every clause has at least one hit (clauses are AND-ed; members within a clause are OR-ed). This prevents single false positives from flipping the state.

```python
STATE_DETECT = {
    State.COMBAT: [
        ["combat_auto_off", "combat_auto_on"],   # clause 1: AUTO button (either state)
        ["combat_speed_1", "combat_speed_2", "combat_speed_3"],  # clause 2: speed indicator
    ],
    ...
}
```

**Sticky state**: state only changes when another state is positively detected. Transient blank frames (loading, animations) keep the current state.

**Grace window**: after every action, `transition_grace_ticks` blank ticks are exempt from the "stuck" counter. This covers loading screens without shortening `tick_interval`.

**Relocate**: when the stuck counter reaches `RELOCATE_INTERVAL` ticks, a full all-states scan is run (expensive — kept rare on purpose).

---

## Template Matching (vision.py)

Uses `cv2.matchTemplate` with `TM_CCOEFF_NORMED`. Templates are matched at multiple scales (`scale_min`..`scale_max` in `scale_steps` steps).

**Scale cache**: after a successful match, the scale is cached per template group. Subsequent ticks search a narrow band around the cached scale first, falling back to the full range only on a miss. This gives a large speedup at steady-state.

**`proc_width`**: the screen is resized to this width before matching. At `960`, the cost is roughly `(original_width/960)^2` times lower. Large UI elements retain sufficient precision at 960px; fine text (e.g. "All Episodes Cleared") is still found reliably.

**Alpha handling** (`assets.py → _load_template_gray`): templates cropped to polygon shapes contain transparent pixels. These are filled with the mean grayscale value of opaque pixels before matching. Without this, transparent corners appear black and corrupt the `TM_CCOEFF_NORMED` (mean-subtracted) calculation — causing low scores even on correct matches.

---

## Asset Registry (assets.py)

`ASSET_GROUPS` maps logical state names to lists of template file stems (without extension). All files live in `assets/` and are `.png`.

Naming conventions:
- `xxx_full` — screenshot includes surrounding elements / border.
- `xxx` — tight crop around the element.
- `xxx_1`, `xxx_2` — different visual variants of the same element (color, gradient). Tried in order; the best score wins.
- `lock_xxx` — locked/inaccessible variant of an element.

`THRESHOLD_OVERRIDES` holds per-group confidence thresholds that differ from `default_threshold`. Override when:
- The template is a large text banner (score peak is narrow → keep threshold around 0.74–0.78 to retain margin).
- The template is a small icon with very distinctive shape (can raise to 0.85+).
- Matching occurs in a constrained state where false positives are impossible (can lower safely).

---

## MomoTalk Automation (momotalk.py)

MomoTalk uses a **sequential task** approach rather than a state machine because the flow is mostly linear. Key design decisions:

**Anchor-based positioning**: The MomoTalk entry on the home screen is located by finding the **Notice (speaker) icon** template (`momotalk_notice`) and applying a fixed pixel offset. The MomoTalk icon itself is not used because its badge number and background vary, making it unstable for template matching.

**Pink "Relationship Story" button**: The in-conversation pink button contains the character's name in small text — this makes it too unstable for template matching across different characters. Instead, the tool uses HSV color detection to find a sufficiently wide pink horizontal stripe in a defined ROI, excluding the title bar area (`y < 250`) which is also pink.

**Reply anchoring**: Reply option text changes each time. The tool finds the `momotalk_reply` template ("| Reply" label) and clicks at a fixed pixel offset below-right — the first reply option is always there regardless of how many options exist.

**Conversation activity detection**: Two consecutive grayscale crops of the conversation panel are compared pixel-by-pixel (average absolute difference). A difference above `diff_thresh` means the other party is typing or new messages arrived. Inactivity for `idle_switch_ticks` consecutive ticks signals the conversation is done.

**Unread detection**: The home-screen red badge is detected purely by color (HSV range for red), not by template. This is robust to badge number changes.

---

## Configuration (config.py)

All configuration is loaded into typed dataclasses. `_build_momotalk` converts YAML lists to tuples for all coordinate fields.

`MomoTalkConfig.ref_width` / `ref_height` define the reference resolution (1920×1080). All `_xy` and `_rel` coordinate fields are in this reference space and are scaled to the actual screen size at runtime.

---

## Adding New Template Groups

1. Take a screenshot in-game (via `--probe --save`).
2. Crop tightly around the element; save as `assets/<name>.png`.
3. Add an entry to `ASSET_GROUPS` in `assets.py`.
4. If the default threshold is wrong, add an override to `THRESHOLD_OVERRIDES`.
5. Use `--probe` to verify the new group is detected correctly.

---

## Notification System (notify.py)

Manual-intervention and completion notices are printed in color to stdout. All other logging is in English via the standard `logging` module. Only the user-facing "stop and do something" messages are localized — kept in `_MESSAGES` in `notify.py` so they are easy to translate without touching business logic.
