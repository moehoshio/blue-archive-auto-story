# Blue Archive Auto Story

Automates main story and event story progression in Blue Archive. Runs on your PC and controls the game via ADB, using OpenCV multi-scale template matching to recognize the current screen state — automatically skipping dialogue, entering and finishing combat, turning pages — until the chapter is fully cleared.

Also supports **MomoTalk** automation: automatically reads through every unread conversation, handles reply choices, and completes attached relationship stories.

---

## Before You Start — Required In-Game Settings

> **These settings must be enabled inside the game before running the tool. Without them the automation will not work correctly.**

Open the game, then enable all three:

| Setting | Where to find it |
|---|---|
| **Auto Next Chapter** | Story settings |
| **Auto Continuous Play** | Story settings |
| **Language: English** | App settings |

The `assets/` template screenshots are captured in English. If the game language differs, template matching will fail.

---

## Prerequisites

### 1. ADB (Android Debug Bridge)

The tool sends taps and captures screenshots through ADB.

**Option A — Phone with USB Debugging**

1. Enable **Developer Options** on your phone (tap Build Number 7 times in About Phone).
2. Enable **USB Debugging** inside Developer Options.
3. Connect your phone to the PC with a USB cable.
4. Run `adb devices` — your device should appear.

**Option B — Android Emulator**

Use any emulator that exposes ADB (BlueStacks, MuMu Player, LDPlayer, Nox, etc.). Most emulators listen on a local TCP port by default; connect with:

```
adb connect 127.0.0.1:5555
```

The port number varies by emulator — check your emulator's settings if `5555` does not work (common alternatives: `7555` for MuMu, `62001` for Nox).

After connecting, run `adb devices` to confirm the device is listed.

**Installing ADB**

- **Windows**: Download [Platform Tools](https://developer.android.com/tools/releases/platform-tools) from Google, extract, and add the folder to your `PATH`. Or install via [Chocolatey](https://chocolatey.org/): `choco install adb`
- **macOS**: `brew install android-platform-tools`
- **Linux**: `sudo apt install adb` (Debian/Ubuntu) or equivalent

### 2. Python 3.9+

Download from [python.org](https://www.python.org/downloads/) or install via your system package manager. Make sure `python --version` returns 3.9 or later.

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/moehoshio/blue-archive-auto-story.git
cd blue-archive-auto-story

# 2. (Recommended) Create a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

Dependencies: `opencv-python`, `numpy`, `PyYAML`

---

## Usage

Make sure the game is open and on the story list screen before running.

```bash
# Automate main story / event story
python main.py

# Automate MomoTalk (relationship conversations)
python main.py --momotalk

# Diagnose: take one screenshot, print what the tool can detect (no taps)
python main.py --probe

# Same as --probe but also save the screenshot to a file
python main.py --probe --save probe.png

# Use a custom config file
python main.py --config myconfig.yaml
```

Press **Ctrl+C** at any time to stop.

### What the tool does vs. what you do

| You do | Tool does |
|---|---|
| Open the game to the story list | Everything after that — entering episodes, skipping dialogue, running combat, turning pages |
| Start the next chapter after one finishes | Detect "All Episodes Cleared" and exit cleanly |
| Manually resolve a stuck/error state | Resume and re-run the tool |

---

## MomoTalk Mode (`--momotalk`)

Runs through every unread conversation:

1. Reads through each conversation automatically.
2. Selects the first available reply option when prompted (any choice works for affection).
3. When a Relationship Story appears, skips it the same way as main story.
4. Collects the reward (TOUCH TO CONTINUE) and returns to the conversation.
5. After finishing a conversation, switches to the next unread one.
6. When no more conversations are reachable in the current list, closes and reopens MomoTalk to refresh.
7. Stops when the main-screen badge (red dot) disappears for several consecutive ticks.

The tool positions itself using the **Notice (speaker icon)** on the home screen as an anchor, not the MomoTalk icon directly, because the badge number changes and the background shifts with the lobby. This makes location stable across different lobby backgrounds.

---

## Configuration

Edit `config.yaml` to adjust behavior. All settings have sensible defaults; you only need to change what doesn't work for your setup.

```yaml
adb:
  path: adb          # Path to the adb executable (full path if not in PATH)
  serial: null       # Device serial; null = use the only connected device

matching:
  scale_min: 0.65    # Minimum template scale to search
  scale_max: 1.6     # Maximum template scale to search
  scale_steps: 17    # Number of scale steps between min and max
  default_threshold: 0.75   # Match confidence threshold (0–1); raise to reduce false positives
  scale_cache_tolerance: 0.08
  proc_width: 960    # Resize screen to this width before matching (0 = no resize); 960 gives ~4x speedup

loop:
  tick_interval: 1.0      # Seconds between each screen check
  tap_delay: 0.5          # Seconds to wait after each tap (for animations to settle)
  idle_ticks_to_end: 30   # Consecutive ticks with nothing detected before giving up
  transition_grace_ticks: 8  # Blank-screen ticks allowed right after an action (covers loading screens)

combat:
  desired_speed: 3   # Target battle speed multiplier (2 or 3)

network:
  max_reconnect: 10  # Max reconnect button taps before asking for manual help

momotalk:
  idle_switch_ticks: 5    # Ticks of conversation inactivity before switching to the next unread
  max_switches: 5         # Max row switches before closing and reopening MomoTalk
  grace_ticks: 10         # Loading grace ticks after entering a story or reward screen
  done_confirm_ticks: 6   # Consecutive ticks with no unread badge before declaring done
  tick_interval: 1.0
  tap_delay: 0.6
  # Coordinates below are in reference resolution 1920x1080 and scale at runtime.
  # Only adjust if taps land in the wrong place on your device.
  notice_home_offset: [142, 10]   # Offset from Notice icon center to MomoTalk entry
  close_xy: [1681, 177]
  unread_tab_xy: [255, 430]
  first_row_xy: [450, 400]
  row_height: 105
  reply_label_offset: [200, 85]

assets_dir: assets
log_level: INFO
save_debug_screens: false   # Set to true to save every screenshot to debug/ for troubleshooting
```

---

## When the Tool Stops — Manual Intervention

The tool will print a colored notice and stop when it cannot continue automatically. Here is what each situation means and what to do:

| Notice | Meaning | What to do |
|---|---|---|
| **Chapter complete** | "All Episodes Cleared" banner detected; the chapter is fully done. | Manually enter the next chapter, then run the tool again. |
| **MomoTalk done** | No more unread conversations found. | Nothing — the task is complete. |
| **Stuck** | No recognizable screen element for too long (e.g. unexpected popup, network error not caught). | Check the game screen, dismiss any popup, then run again. |
| **Network reconnect failed** | The reconnect button appeared more than `max_reconnect` times in a row. | Check your internet connection and the game, then run again. |
| **Battle failed, returned to home** | The game returned to the home screen after a combat loss. | Re-navigate to the story chapter in-game, then run again. |
| **Mobilize stall** | The "Deploy" button was tapped multiple times but battle never started. | Check that your team formation is set, then run again. |

---

## Troubleshooting & FAQ

### "adb: command not found" / "adb is not recognized"

ADB is not in your `PATH`. Either:
- Add the Platform Tools folder to your system `PATH`, or
- Set `adb.path` in `config.yaml` to the full path of the executable (e.g. `C:\platform-tools\adb.exe`).

### "error: no devices/emulators found"

The device is not connected or not authorized.

- USB: run `adb devices` — if the device shows as `unauthorized`, unlock your phone and tap **Allow** on the authorization prompt.
- Emulator: run `adb connect 127.0.0.1:<port>` with the correct port for your emulator.

### Multiple devices connected

If you have more than one device (or emulator), set `adb.serial` in `config.yaml` to the exact serial shown by `adb devices`.

### Template matching always misses / wrong taps

The template images were captured at a specific resolution and in English. Common causes:

- **Wrong game language** — set the in-game language to **English**.
- **Resolution mismatch** — the tool scales templates automatically, but if your screen resolution is very unusual, you may need to retake screenshots and replace the files in `assets/`.
- **Threshold too high** — lower `matching.default_threshold` slightly (e.g. from `0.75` to `0.70`).
- Use `--probe` to see what the tool detects on the current screen and what scores it gets.

### The tool gets stuck on the combat screen

Ensure the in-game **AUTO** and **speed** controls are visible. Some event stages lock AUTO — the tool will tap at most 3 times and then wait if AUTO cannot be enabled.

### MomoTalk taps land in the wrong place

The MomoTalk layout uses scaled coordinates from a 1920×1080 reference. If your emulator or phone uses a non-standard aspect ratio or scaling, the taps may be off. Adjust the coordinate values under `momotalk:` in `config.yaml` (see the comments above each entry for what each controls).

### How do I see what the tool is detecting?

Run `python main.py --probe` to take a single screenshot and print every template group with its match score and position. Add `--save probe.png` to save the screenshot.

Set `save_debug_screens: true` in `config.yaml` to save every tick's screenshot to the `debug/` folder.

### Can I run this on multiple devices at once?

Yes — run a separate instance per device, each with its own `config.yaml` specifying a different `adb.serial`.

---

## Project Structure

```
main.py              Entry point / --probe command
config.yaml          User configuration
assets/              Template screenshot images
src/
  config.py          Config loading (dataclasses)
  adb.py             ADB screenshot + tap
  vision.py          Multi-scale template matching (with scale cache)
  assets.py          Logical state name → template file registry
  automator.py       Reactive state machine (main/event story)
  momotalk.py        MomoTalk automation
  logging_setup.py   Logging setup
  notify.py          Colored manual-intervention notices
```

---

## License

See [LICENSE](LICENSE) if present. This tool is for personal use only. Use it responsibly and in accordance with the game's terms of service.
