#!/usr/bin/env python3
"""Interactive helper for capturing template images.

Usage::

    python tools/capture_template.py --name battle/sortie --roi 950,580,330,140

This is a thin wrapper around ``bass capture`` so people without the package
installed can still run it from the repo root.
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

    # Forward to the `capture` sub-command.
    cli.main(args=["capture", *sys.argv[1:]], standalone_mode=True)


if __name__ == "__main__":
    main()
