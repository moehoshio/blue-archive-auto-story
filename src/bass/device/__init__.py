"""Device sub-package: ADB client and resolution helpers."""

from .adb_client import AdbClient, DeviceInfo
from .resolution import CoordinateScaler

__all__ = ["AdbClient", "DeviceInfo", "CoordinateScaler"]
