"""Centralized logging using loguru with a stdlib fallback.

We keep loguru optional so the package (and its tests) work even if it
isn't installed. Importing loguru lazily lets unit tests run in minimal
environments.
"""

from __future__ import annotations

import logging
import sys
from typing import Any


class _StdlibLogger:
    """Tiny shim mimicking the few loguru methods we use."""

    def __init__(self, name: str = "bass") -> None:
        self._log = logging.getLogger(name)
        if not self._log.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(
                logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
            )
            self._log.addHandler(handler)
            self._log.setLevel(logging.INFO)

    def debug(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log.debug(str(msg), *args)

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log.info(str(msg), *args)

    def warning(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log.warning(str(msg), *args)

    def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log.error(str(msg), *args)

    def exception(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log.exception(str(msg), *args)

    def bind(self, **_: Any) -> _StdlibLogger:
        return self


def get_logger() -> Any:
    """Return a logger; uses loguru if available."""
    try:
        from loguru import logger as _loguru  # type: ignore[import-not-found]

        return _loguru
    except Exception:  # pragma: no cover – fallback path
        return _StdlibLogger()


def configure(level: str = "INFO") -> None:
    """Configure the root logger / loguru sink."""
    try:
        from loguru import logger as _loguru  # type: ignore[import-not-found]

        _loguru.remove()
        _loguru.add(
            sys.stderr,
            level=level,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <7}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
            ),
        )
    except Exception:  # pragma: no cover
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        )


log = get_logger()
