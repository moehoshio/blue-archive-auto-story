#!/usr/bin/env python3
"""Replay a folder of screenshots through the StateDetector.

Useful for tuning thresholds / regions without a connected device. Wraps the
``bass replay`` sub-command for convenience.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "src"
    if src.is_dir():
        sys.path.insert(0, str(src))
    from bass.cli import cli

    cli.main(args=["replay", *sys.argv[1:]], standalone_mode=True)


if __name__ == "__main__":
    main()
