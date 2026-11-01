import json
import os

DEFAULTS = {
    "airings": list,
    "bouncer": dict,
    "resolved": dict,
    "overrides": dict,
    "meta": dict,
}


class State:
    """Everything the station remembers, kept as small JSON files in state/."""

    def __init__(self, directory: str):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)
        for name, kind in DEFAULTS.items():
            path = os.path.join(directory, f"{name}.json")
            value = kind()
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    value = json.load(fh)
            setattr(self, name, value)
        self.meta.setdefault("episode_no", 0)
        self.meta.setdefault("since_wildcard", 0)
        self.meta.setdefault("added", [])

    def save(self):
        for name in DEFAULTS:
            path = os.path.join(self.dir, f"{name}.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(getattr(self, name), fh, indent=1, ensure_ascii=False, sort_keys=name != "airings")
                fh.write("\n")
            os.replace(tmp, path)
