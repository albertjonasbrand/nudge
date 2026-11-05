"""A rolling transcript held only in RAM."""

from __future__ import annotations

import threading
import time
from collections import deque


class RingBuffer:
    """Keeps (timestamp, text) segments for the last `seconds` seconds."""

    def __init__(self, seconds: float = 60.0, tail_seconds: float = 6.0):
        self.seconds = seconds
        self.tail_seconds = tail_seconds
        self._segments: deque[tuple[float, str]] = deque()
        self._lock = threading.Lock()

    def push(self, text: str, when: float | None = None) -> None:
        text = text.strip()
        if not text:
            return
        now = when if when is not None else time.monotonic()
        with self._lock:
            self._segments.append((now, text))
            self._trim(now)

    def _trim(self, now: float) -> None:
        cutoff = now - self.seconds
        while self._segments and self._segments[0][0] < cutoff:
            self._segments.popleft()

    def snapshot(self, now: float | None = None) -> tuple[str, str]:
        """Return (context, tail): everything, and just the last few seconds."""
        now = now if now is not None else time.monotonic()
        with self._lock:
            self._trim(now)
            segs = list(self._segments)
        context = " ".join(t for _, t in segs)
        tail_cut = now - self.tail_seconds
        tail = " ".join(t for ts, t in segs if ts >= tail_cut)
        if not tail and segs:
            tail = segs[-1][1]
        return context, tail

    def clear(self) -> None:
        with self._lock:
            self._segments.clear()
