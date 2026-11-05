"""The personal lexicon: his people, places, and things, plus words he confirmed."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import yaml

DEFAULT_PATH = Path("config/lexicon.yaml")
EXAMPLE_PATH = Path("config/lexicon.example.yaml")
MAX_CONFIRMED = 300


class Lexicon:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self.data: dict = {"people": [], "places": [], "life": [], "confirmed": []}
        self.load()

    def load(self) -> None:
        src = self.path if self.path.exists() else EXAMPLE_PATH
        if src.exists():
            loaded = yaml.safe_load(src.read_text()) or {}
            for key in self.data:
                self.data[key] = list(loaded.get(key) or [])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True))

    def confirm(self, word: str) -> None:
        """Record a word he actually used after a nudge; boosts it next time."""
        word = word.strip()
        if not word:
            return
        now = _dt.datetime.now().isoformat(timespec="seconds")
        confirmed = self.data["confirmed"]
        for entry in confirmed:
            if entry.get("word", "").lower() == word.lower():
                entry["count"] = int(entry.get("count", 1)) + 1
                entry["last"] = now
                break
        else:
            confirmed.append({"word": word, "count": 1, "last": now})
        confirmed.sort(key=lambda e: (-int(e.get("count", 1)), e.get("last", "")))
        del confirmed[MAX_CONFIRMED:]
        self.save()

    def as_prompt_text(self) -> str:
        """Compact text block for the system prompt."""
        lines: list[str] = []
        for section, label in (("people", "People"), ("places", "Places"), ("life", "His life")):
            items = self.data.get(section) or []
            if not items:
                continue
            parts = []
            for e in items:
                w = e.get("word", "").strip()
                n = e.get("note", "").strip()
                parts.append(f"{w} ({n})" if n else w)
            lines.append(f"{label}: " + ", ".join(parts))
        confirmed = [e["word"] for e in (self.data.get("confirmed") or [])[:60]]
        if confirmed:
            lines.append("Words he often needs: " + ", ".join(confirmed))
        return "\n".join(lines)

    def all_words(self) -> set[str]:
        out: set[str] = set()
        for section in ("people", "places", "life", "confirmed"):
            for e in self.data.get(section) or []:
                out.add(e.get("word", "").strip().lower())
        out.discard("")
        return out
