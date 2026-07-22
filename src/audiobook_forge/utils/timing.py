"""Small timing utilities."""

from __future__ import annotations

import time
from types import TracebackType


class Stopwatch:
    """Context manager / helper measuring wall-clock elapsed seconds.

    Example:
        >>> with Stopwatch() as sw:
        ...     do_work()
        >>> print(sw.elapsed)
    """

    def __init__(self) -> None:
        self._start = 0.0
        self._end: float | None = None

    def __enter__(self) -> "Stopwatch":
        self._start = time.perf_counter()
        self._end = None
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._end = time.perf_counter()

    @property
    def elapsed(self) -> float:
        end = self._end if self._end is not None else time.perf_counter()
        return end - self._start
