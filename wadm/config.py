import os
import re
from dataclasses import dataclass, field
from typing import Optional

import yaml

ROOT = os.environ.get("WADM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TIERS = ("love", "fine", "noise", "wildcard")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_yaml(name: str) -> dict:
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class Show:
    name: str
    tier: str
    apple_id: Optional[int] = None
    feed: Optional[str] = None
    tags: list = field(default_factory=list)
    base_tier: str = ""
    more: int = 0
    less: int = 0

    @property
    def key(self) -> str:
        return slug(self.name)

    def has(self, tag: str) -> bool:
        return tag in (self.tags or [])


def _show_from(d: dict) -> Show:
    tier = str(d.get("tier", "wildcard")).lower()
    if tier not in TIERS:
        raise ValueError(f"{d.get('name')}: unknown tier '{tier}'")
    return Show(
        name=str(d["name"]),
        tier=tier,
        apple_id=d.get("apple_id"),
        feed=d.get("feed"),
        tags=list(d.get("tags") or []),
        base_tier=tier,
    )


def load_roster(state) -> list:
    """shows.yaml plus monthly additions, with vote results applied."""
    raw = list(load_yaml("shows.yaml").get("shows") or [])
    raw += [dict(a, tier=a.get("tier", "wildcard")) for a in state.meta.get("added", [])]
    roster, seen = [], set()
    for d in raw:
        show = _show_from(d)
        if show.key in seen:
            continue
        seen.add(show.key)
        ov = state.overrides.get(show.key, {})
        show.more = int(ov.get("more", 0))
        show.less = int(ov.get("less", 0))
        if ov.get("tier"):
            show.tier = ov["tier"]
        roster.append(show)
    return roster


def multiplier(show: Show, votes_cfg: dict) -> float:
    step = float(votes_cfg.get("step", 0.25))
    lo = float(votes_cfg.get("min_multiplier", 0.25))
    hi = float(votes_cfg.get("max_multiplier", 2.0))
    return max(lo, min(hi, 1 + step * (show.more - show.less)))
