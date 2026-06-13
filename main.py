"""Entry point.

Usage:
  python main.py                       # Run auto story (main/event)
  python main.py --momotalk            # Run MomoTalk automation
  python main.py --config x.yaml      # Use a custom config file
  python main.py --probe               # Take one screenshot, print detected elements (no taps)
  python main.py --probe --save out.png  # Same, and save the screenshot
"""
from __future__ import annotations

import argparse
import logging
import sys

# Windows terminals are often cp950; force stdout to utf-8 so ✓ / ⚠ characters don't crash.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from src.adb import Adb
from src.assets import THRESHOLD_OVERRIDES, load_assets
from src.automator import StoryAutomator
from src.config import load_config
from src.logging_setup import setup_logging
from src.vision import TemplateMatcher, to_gray

log = logging.getLogger("main")


def probe(cfg, save: str | None) -> None:
    """Take one screenshot, match every group, print results — no taps."""
    adb = Adb(cfg.adb)
    adb.ensure_device()
    bgr = adb.screencap()
    gray = to_gray(bgr)
    if save:
        import cv2
        cv2.imwrite(save, bgr)
        log.info("screenshot saved: %s (%dx%d)", save, bgr.shape[1], bgr.shape[0])

    matcher = TemplateMatcher(cfg.matching)
    groups = load_assets(cfg.assets_dir)
    log.info("screen size: %dx%d", bgr.shape[1], bgr.shape[0])
    print(f"{'group':<24}{'hit':<6}{'score':<8}{'scale':<8}pos")
    for name, tpls in groups.items():
        if not tpls:
            continue
        thr = THRESHOLD_OVERRIDES.get(name)
        m = matcher.find(gray, tpls, thr)
        if m:
            print(f"{name:<24}{'✓':<6}{m.score:<8.3f}{m.scale:<8.2f}({m.x},{m.y})")
        else:
            print(f"{name:<24}{'·':<6}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Blue Archive auto-story tool")
    parser.add_argument("--config", default="config.yaml", help="path to config file")
    parser.add_argument("--probe", action="store_true", help="detect only, no taps (for tuning thresholds/scales)")
    parser.add_argument("--save", default=None, help="save the probe screenshot to this path")
    parser.add_argument("--momotalk", action="store_true", help="run MomoTalk automation instead of main story")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.log_level)

    if args.probe:
        probe(cfg, args.save)
        return

    adb = Adb(cfg.adb)
    if args.momotalk:
        from src.momotalk import MomoTalkAutomator
        MomoTalkAutomator(cfg, adb).run()
        return

    automator = StoryAutomator(cfg, adb)
    automator.run()


if __name__ == "__main__":
    main()
