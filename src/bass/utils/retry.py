"""Generic retry helper used by Action and engine code."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from .logging import log

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    delay_sec: float = 0.5
    backoff: float = 1.5

    def sleep_for(self, attempt_index: int) -> float:
        # attempt_index is 0-based
        return self.delay_sec * (self.backoff**attempt_index)


def retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    on_exception: tuple[type[BaseException], ...] = (Exception,),
    description: str = "operation",
) -> T:
    """Call ``fn`` with retries.

    Re-raises the last exception if all attempts fail.
    """
    pol = policy or RetryPolicy()
    last: BaseException | None = None
    for i in range(pol.attempts):
        try:
            return fn()
        except on_exception as exc:  # noqa: PERF203 – clarity over micro-opt
            last = exc
            sleep = pol.sleep_for(i)
            log.warning(f"{description} failed (attempt {i + 1}/{pol.attempts}): {exc!r}")
            if i + 1 < pol.attempts:
                time.sleep(sleep)
    assert last is not None  # pragma: no cover – attempts >= 1
    raise last
