"""ADB control: screencap and tap via standard adb (screencap + input tap)."""
from __future__ import annotations

import logging
import subprocess
from typing import List, Optional

import cv2
import numpy as np

from .config import AdbConfig

log = logging.getLogger(__name__)


class AdbError(RuntimeError):
    pass


class Adb:
    def __init__(self, cfg: AdbConfig):
        self.cfg = cfg

    def _base_cmd(self) -> List[str]:
        cmd = [self.cfg.path]
        if self.cfg.serial:
            cmd += ["-s", self.cfg.serial]
        return cmd

    def _run(self, args: List[str], capture: bool = False, timeout: float = 20.0) -> bytes:
        cmd = self._base_cmd() + args
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except FileNotFoundError as e:
            raise AdbError(f"adb executable not found: {self.cfg.path}") from e
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"adb command timed out: {' '.join(args)}") from e
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", "ignore").strip()
            raise AdbError(f"adb command failed ({' '.join(args)}): {err}")
        return proc.stdout or b""

    def ensure_device(self) -> None:
        """Verify a device is available; raise AdbError otherwise."""
        out = self._run(["get-state"], capture=True).decode("utf-8", "ignore").strip()
        if out != "device":
            raise AdbError(f"device not ready, adb get-state = '{out}'")
        log.info("ADB device ready: %s", self.cfg.serial or "(default)")

    def screencap(self) -> np.ndarray:
        """Capture a screenshot; return a BGR image. Uses exec-out to avoid Windows CRLF corruption."""
        raw = self._run(["exec-out", "screencap", "-p"], capture=True)
        if not raw:
            raise AdbError("screencap returned empty data")
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbError("failed to decode screencap image")
        return img

    def tap(self, x: int, y: int) -> None:
        log.debug("tap (%d, %d)", x, y)
        self._run(["shell", "input", "tap", str(int(x)), str(int(y))])
