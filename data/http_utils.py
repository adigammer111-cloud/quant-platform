"""Shared retry / backoff / throttling helpers for network-backed providers."""
from __future__ import annotations

import functools
import logging
import random
import threading
import time
from typing import Callable, TypeVar

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Throttler:
    """Enforces a minimum interval between successive calls (process-wide)."""

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            remaining = self._min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_call = time.monotonic()


_default_throttler = Throttler(settings.http_min_interval_seconds)


def retry_with_backoff(
    max_retries: int | None = None,
    base_delay: float | None = None,
    throttle: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator adding exponential backoff with jitter and optional
    process-wide request throttling to a network call.
    """
    retries = max_retries if max_retries is not None else settings.http_max_retries
    delay0 = base_delay if base_delay is not None else settings.http_backoff_base_seconds

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(1, retries + 1):
                if throttle:
                    _default_throttler.wait()
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt == retries:
                        break
                    sleep_for = delay0 * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning(
                        "%s failed (attempt %d/%d): %s - retrying in %.1fs",
                        func.__name__,
                        attempt,
                        retries,
                        exc,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
