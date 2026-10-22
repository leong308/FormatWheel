"""Per-user preferences. Nothing is written beside the installed executable."""
from __future__ import annotations

import json
import os
from pathlib import Path

CREWS = {
    "online": ("线上模式 · 蓝 / Online", "#3380e6"),
    "michael": ("麦克 · 天蓝 / Michael", "#66b5d4"),
    "franklin": ("富兰克林 · 绿 / Franklin", "#6bd173"),
    "trevor": ("崔佛 · 橙 / Trevor", "#ff9947"),
}
SIZES = {"small": ("小 / Small", 235), "medium": ("中 / Medium", 285), "large": ("大 / Large", 330)}


class Settings:
    defaults = {"crew": "online", "size": "medium", "icons": "formats", "sound": True,
                "blur": True, "banner": True, "welcomed": False, "recents": []}

    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.environ.get("APPDATA", Path.home() / ".config")) / "FormatWheel" / "settings.json"
        self.values = dict(self.defaults)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.values.update({k: v for k, v in loaded.items() if k in self.defaults})
        except (OSError, ValueError):
            pass
        for name, choices in (("crew", CREWS), ("size", SIZES), ("icons", {"formats", "weapons"})):
            if self.values[name] not in choices:
                self.values[name] = self.defaults[name]
        if not isinstance(self.values["recents"], list):
            self.values["recents"] = []

    def get(self, key):
        return self.values.get(key, self.defaults.get(key))

    def set(self, key, value):
        self.values[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @property
    def accent(self):
        return CREWS[self.get("crew")][1]

    @property
    def radius(self):
        return SIZES[self.get("size")][1]

    def add_recent(self, paths):
        fresh = [str(Path(p).absolute()) for p in paths]
        self.set("recents", list(dict.fromkeys(fresh + self.get("recents")))[:8])
