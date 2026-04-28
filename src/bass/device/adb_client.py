"""Thin wrapper around :mod:`adbutils` exposing only the operations we need.

The wrapper isolates the rest of the codebase from adbutils' API surface and
makes it trivial to stub for unit tests (see ``tests/conftest.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..utils.logging import log

if TYPE_CHECKING:  # pragma: no cover
    pass


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    state: str
    model: str = ""
    width: int = 0
    height: int = 0

    @property
    def resolution(self) -> tuple[int, int]:
        return self.width, self.height


class _DeviceProto(Protocol):  # pragma: no cover – typing helper
    serial: str

    def shell(self, cmd: str, timeout: float | None = ...) -> str: ...
    def screenshot(self) -> object: ...  # PIL.Image
    def click(self, x: int, y: int) -> None: ...
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = ...) -> None: ...
    def keyevent(self, key: int | str) -> None: ...


class AdbClient:
    """High-level ADB client.

    Parameters
    ----------
    serial:
        Serial / "host:port". ``""`` (default) auto-picks the first device.
    host, port:
        ADB server endpoint. Defaults to the local server (127.0.0.1:5037).
    device:
        Optional pre-built adbutils Device, used by tests.
    """

    def __init__(
        self,
        serial: str = "",
        host: str = "127.0.0.1",
        port: int = 5037,
        *,
        device: _DeviceProto | None = None,
    ) -> None:
        self._serial = serial
        self._host = host
        self._port = port
        self._device: _DeviceProto | None = device

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def _ensure_device(self) -> _DeviceProto:
        if self._device is not None:
            return self._device
        try:
            import adbutils  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "adbutils is not installed. `pip install adbutils` (or install bass with extras)."
            ) from e

        adb = adbutils.AdbClient(host=self._host, port=self._port)
        if self._serial:
            # If serial looks like host:port and is not in `adb devices`, try connect first.
            if ":" in self._serial:
                try:
                    adb.connect(self._serial)
                except Exception as e:  # pragma: no cover
                    log.warning(f"adb connect {self._serial} failed: {e!r}")
            self._device = adb.device(serial=self._serial)
        else:
            devices = adb.device_list()
            if not devices:
                raise RuntimeError(
                    "No ADB devices found. Connect a device and check `adb devices`."
                )
            self._device = devices[0]
            log.info(f"Auto-selected ADB device: {self._device.serial}")
        return self._device

    # ------------------------------------------------------------------
    # Read-only
    # ------------------------------------------------------------------
    @staticmethod
    def list_devices(host: str = "127.0.0.1", port: int = 5037) -> list[DeviceInfo]:
        try:
            import adbutils  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("adbutils is not installed.") from e
        adb = adbutils.AdbClient(host=host, port=port)
        infos: list[DeviceInfo] = []
        for d in adb.device_list():
            try:
                wm = d.shell("wm size")
                # Example: "Physical size: 1280x720"
                w, h = 0, 0
                for line in wm.splitlines():
                    if "x" in line and ":" in line:
                        try:
                            wh = line.split(":", 1)[1].strip()
                            w_s, h_s = wh.split("x")
                            w, h = int(w_s), int(h_s)
                            break
                        except Exception:  # noqa: BLE001
                            continue
                model = d.shell("getprop ro.product.model").strip()
                infos.append(
                    DeviceInfo(serial=d.serial, state="device", model=model, width=w, height=h)
                )
            except Exception as exc:  # pragma: no cover
                log.warning(f"Failed to introspect device {d.serial}: {exc!r}")
                infos.append(DeviceInfo(serial=d.serial, state="unknown"))
        return infos

    def is_connected(self) -> bool:
        try:
            d = self._ensure_device()
            d.shell("echo ok")
            return True
        except Exception as exc:  # pragma: no cover
            log.warning(f"is_connected probe failed: {exc!r}")
            return False

    def resolution(self) -> tuple[int, int]:
        d = self._ensure_device()
        out = d.shell("wm size")
        for line in out.splitlines():
            if ":" in line and "x" in line:
                try:
                    wh = line.split(":", 1)[1].strip()
                    w_s, h_s = wh.split("x")
                    return int(w_s), int(h_s)
                except Exception:  # noqa: BLE001
                    continue
        raise RuntimeError(f"could not parse `wm size` output: {out!r}")

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------
    def screencap_png(self) -> bytes:
        """Return the current screen as PNG-encoded bytes."""
        d = self._ensure_device()
        # adbutils Device.screenshot() returns a PIL Image.
        img = d.screenshot()
        import io

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def screencap_ndarray(self):  # -> np.ndarray (BGR)
        """Return the current screen as an OpenCV-compatible BGR ndarray."""
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]

        d = self._ensure_device()
        img = d.screenshot()
        arr = np.array(img)  # RGB or RGBA
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        elif arr.ndim == 3 and arr.shape[2] == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return arr

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def tap(self, x: int, y: int) -> None:
        d = self._ensure_device()
        log.debug(f"tap ({x},{y})")
        d.click(int(x), int(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        d = self._ensure_device()
        log.debug(f"swipe ({x1},{y1})->({x2},{y2}) {duration_ms}ms")
        d.swipe(int(x1), int(y1), int(x2), int(y2), duration_ms / 1000.0)

    def back(self) -> None:
        d = self._ensure_device()
        d.keyevent("KEYCODE_BACK")

    def home(self) -> None:
        d = self._ensure_device()
        d.keyevent("KEYCODE_HOME")
