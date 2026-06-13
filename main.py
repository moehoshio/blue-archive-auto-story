"""進入點。

用法:
  python main.py                 # 啟動自動劇情 (主線/活動)
  python main.py --momotalk      # 啟動好感劇情 (MomoTalk) 自動化
  python main.py --config x.yaml # 指定設定檔
  python main.py --probe         # 只截一次圖, 列出偵測到的所有元素 (不動作), 供調參
  python main.py --probe --save out.png  # 同時把截圖存檔
"""
from __future__ import annotations

import argparse
import logging
import sys

# Windows 終端常為 cp950, 直接 print ✓ 等字元會崩潰; 強制 stdout 用 utf-8。
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
    """截一次圖, 對每個群組做匹配並列出結果, 不執行任何點擊。"""
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
    parser = argparse.ArgumentParser(description="Blue Archive 自動劇情工具")
    parser.add_argument("--config", default="config.yaml", help="設定檔路徑")
    parser.add_argument("--probe", action="store_true", help="只偵測不動作 (調參用)")
    parser.add_argument("--save", default=None, help="probe 時把截圖存到此路徑")
    parser.add_argument("--momotalk", action="store_true", help="跑好感劇情 (MomoTalk) 而非主線")
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
