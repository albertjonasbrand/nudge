"""Settings: config/settings.yaml with dot access, env overrides for paths."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("NUDGE_ROOT", Path(__file__).resolve().parent.parent))
SETTINGS = Path(os.environ.get("NUDGE_SETTINGS", ROOT / "config" / "settings.yaml"))


class Section(dict):
    def __getattr__(self, k: str) -> Any:
        v = self.get(k)
        return Section(v) if isinstance(v, dict) else v


def load(path: Path | str | None = None) -> Section:
    p = Path(path) if path else SETTINGS
    data = yaml.safe_load(p.read_text()) if p.exists() else {}
    cfg = Section(data or {})
    # resolve relative paths against the repo root so the service can run from anywhere
    for sec, key in (("model", "path"), ("log", "path")):
        v = cfg.get(sec, {}).get(key)
        if v and not os.path.isabs(v):
            cfg[sec][key] = str(ROOT / v)
    return cfg
