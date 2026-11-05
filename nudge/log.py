"""The stall log: off by default, CSV, for his therapist.

One row per click: when, his last few seconds, the three candidates, which
one he used (filled in when he says it or taps it), and how long it took.
Never the full transcript, never audio.
"""

from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

FIELDS = ["time", "tail", "cand1", "cand2", "cand3", "used", "ms", "more"]


class StallLog:
    def __init__(self, path: str | Path, enabled: bool = False):
        self.path = Path(path)
        self.enabled = enabled
        self._last_row: dict | None = None

    def record(self, tail: str, words: list[str], ms: float, more: int = 0) -> None:
        if not self.enabled:
            return
        row = {"time": _dt.datetime.now().isoformat(timespec="seconds"), "tail": tail,
               "cand1": words[0] if len(words) > 0 else "",
               "cand2": words[1] if len(words) > 1 else "",
               "cand3": words[2] if len(words) > 2 else "",
               "used": "", "ms": round(ms), "more": more}
        self._write(row)
        self._last_row = row

    def mark_used(self, word: str) -> None:
        """Rewrite the last row with the word he picked (small file, so rewrite is fine)."""
        if not self.enabled or not self._last_row or not self.path.exists():
            return
        rows = list(csv.DictReader(self.path.open()))
        for r in reversed(rows):
            if r["time"] == self._last_row["time"] and r["tail"] == self._last_row["tail"]:
                r["used"] = word
                break
        with self.path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)

    def _write(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        with self.path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)

    def wipe(self) -> None:
        if self.path.exists():
            self.path.unlink()
