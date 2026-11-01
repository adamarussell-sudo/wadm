"""The program director: decides what airs in each block."""
import hashlib
import random
import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import TIERS, multiplier
from .sources import fetch, resolve

BLOCK_START = {"am": time(5, 0), "pm": time(16, 0)}
JUNK_TITLE = re.compile(r"^\s*(introducing|trailer|teaser|announcement|coming soon)\b", re.I)
SERIES_NOISE = re.compile(r"\b(cbs|radio|mystery|theater|theatre|cbsrmt|rmt|old|time|otr|episode|ep|e)\b")


def series_title(title: str) -> str:
    """Strip numbers and series boilerplate so re-uploads of the same old show match."""
    t = re.sub(r"[^a-z ]+", " ", title.lower())
    t = SERIES_NOISE.sub(" ", t)
    return " ".join(t.split())


class Programmer:
    def __init__(self, station, roster, state, session, bouncer, now, log=print):
        self.station = station
        self.roster = [s for s in roster if s.tier in TIERS]
        self.state = state
        self.session = session
        self.bouncer = bouncer
        self.now = now
        self.log = log
        self.tz = ZoneInfo(station.get("timezone", "America/New_York"))
        self.tiers = station["tiers"]
        self.votes_cfg = station.get("votes", {})
        self._eps = {}
        self.dead = set()

    # ---- episodes --------------------------------------------------------

    def episodes(self, show):
        if show.key not in self._eps:
            info = resolve(show, self.state, self.session, self.now, self.log)
            self._eps[show.key] = fetch(show, info, self.session, self.log) if info else ([], None)
        return self._eps[show.key]

    def airable(self, ep) -> bool:
        if ep.kind == "trailer" or JUNK_TITLE.match(ep.title):
            return False
        min_s = int(self.station.get("min_minutes", 8)) * 60
        return ep.seconds is None or ep.seconds >= min_s

    def pick_episode(self, show, rng, block_day: date):
        eps, art = self.episodes(show)
        not_yet = self.now + timedelta(hours=1)  # some feeds list episodes scheduled for later
        eps = [e for e in eps if self.airable(e) and not (e.published and e.published > not_yet)]
        if not eps:
            return None
        last_aired = {}
        for a in self.state.airings:
            if a["show"] == show.key:
                last_aired[a["guid"]] = a["date"]
        series_aired = set()
        if show.has("mystery"):
            series_aired = {series_title(a["title"]) for a in self.state.airings if a.get("mystery")}

        def already_heard(e):
            if not series_aired:
                return False
            st = series_title(e.title)
            return len(st) >= 8 and any(st == s or (len(s) >= 8 and (st in s or s in st)) for s in series_aired)

        fresh_cut = self.now - timedelta(days=int(self.station.get("fresh_days", 10)))
        repeat_cut = (block_day - timedelta(days=int(self.station.get("no_repeat_days", 365)))).isoformat()
        fresh = sorted(
            [e for e in eps if e.published and e.published >= fresh_cut and e.guid not in last_aired and not already_heard(e)],
            key=lambda e: e.published,
            reverse=True,
        )
        fresh_ids = {e.guid for e in fresh}
        archive = [
            e for e in eps
            if e.guid not in fresh_ids
            and (e.guid not in last_aired or last_aired[e.guid] < repeat_cut)
            and not already_heard(e)
        ]
        rng.shuffle(archive)
        order = fresh + archive
        if not order:  # the whole catalog has aired: least recently aired first
            order = sorted(eps, key=lambda e: last_aired.get(e.guid, ""))
        for e in order[:10]:
            ok, _ = self.bouncer.judge(e, self.now.isoformat())
            if ok:
                return e, art
        return None

    # ---- shows -----------------------------------------------------------

    def week_counts(self, block_day: date) -> Counter:
        start = (block_day - timedelta(days=6)).isoformat()
        return Counter(
            a["show"] for a in self.state.airings
            if a["date"] >= start and a["kind"] in ("day", "wildcard")
        )

    def weight(self, show) -> float:
        return float(self.tiers[show.tier]["weight"]) * multiplier(show, self.votes_cfg)

    def draw(self, pool, rng, exclude, counts=None):
        cands = []
        for s in pool:
            if s.key in exclude or s.key in self.dead:
                continue
            if counts is not None and counts[s.key] >= int(self.tiers[s.tier]["max_per_week"]):
                continue
            cands.append(s)
        if not cands:
            return None
        weights = [self.weight(s) for s in cands]
        return rng.choices(cands, weights=weights, k=1)[0]

    def fill(self, attempts, rng, block_day):
        """Try each (kind, pool, exclude, counts) in order until a show yields an episode."""
        for kind, pool, exclude, counts in attempts:
            tried = set(exclude)
            while True:
                show = self.draw(pool, rng, tried, counts)
                if not show:
                    break
                tried.add(show.key)
                got = self.pick_episode(show, rng, block_day)
                if got:
                    return kind, show, got
                self.dead.add(show.key)
        return None

    # ---- blocks ----------------------------------------------------------

    def block_start(self, block: str, day: date) -> datetime:
        return datetime.combine(day, BLOCK_START[block], tzinfo=self.tz)

    def build(self, block: str, day: date) -> list:
        block_id = f"{day.isoformat()}-{block}"
        if any(a["block"] == block_id for a in self.state.airings):
            self.log(f"{block_id} already on the schedule")
            return []
        rng = random.Random(int(hashlib.sha256(block_id.encode()).hexdigest()[:12], 16))
        bcfg = self.station["blocks"][block]
        night_tags = list(bcfg.get("night_slots") or [])
        day_slots = int(bcfg["slots"]) - len(night_tags)
        every = int(self.station.get("wildcard_every", 5))
        today = {a["show"] for a in self.state.airings if a["date"] == day.isoformat()}
        counts = self.week_counts(day)
        picked = set()
        start = self.block_start(block, day)
        aired = []

        daytime = [s for s in self.roster if not s.has("night_only")]
        regular = [s for s in daytime if s.tier in ("love", "fine", "noise")]
        wild = [s for s in daytime if s.tier == "wildcard"]

        for _ in range(day_slots):
            want_wild = self.state.meta["since_wildcard"] >= every - 1
            attempts = []
            if want_wild:
                attempts.append(("wildcard", wild, picked | today, counts))
            attempts += [
                ("day", regular, picked | today, counts),   # normal rules
                ("day", regular, picked | today, None),     # every show at its cap: lift caps
                ("day", regular, set(picked), None),        # still nothing: allow a second play today
            ]
            got = self.fill(attempts, rng, day)
            if not got:
                self.log(f"  {block_id}: nothing airable for a daytime slot")
                continue
            kind, show, (ep, art) = got
            self.state.meta["since_wildcard"] = 0 if kind == "wildcard" else self.state.meta["since_wildcard"] + 1
            aired.append(self.record(block_id, day, len(aired), kind, show, ep, art, start))
            picked.add(show.key)
            today.add(show.key)
            counts[show.key] += 1

        after_dark = [s for s in self.roster if any(s.has(t) for t in night_tags)]
        for tag in night_tags:
            pool = [s for s in self.roster if s.has(tag)]
            last = self.last_in_slot(tag)
            attempts = [
                ("night", pool, picked | ({last} if last else set()), None),  # not the same show as last night
                ("night", pool, set(picked), None),
                ("night", after_dark, set(picked), None),                     # this slot's pool is empty
            ]
            got = self.fill(attempts, rng, day)
            if not got:
                self.log(f"  {block_id}: nothing airable for the {tag} slot")
                continue
            kind, show, (ep, art) = got
            rec = self.record(block_id, day, len(aired), kind, show, ep, art, start)
            rec["night_tag"] = tag
            aired.append(rec)
            picked.add(show.key)
        return aired

    def last_in_slot(self, tag):
        for a in reversed(self.state.airings):
            if a.get("night_tag") == tag:
                return a["show"]
        return None

    def record(self, block_id, day, slot, kind, show, ep, art, start):
        self.state.meta["episode_no"] += 1
        rec = {
            "block": block_id,
            "date": day.isoformat(),
            "slot": slot,
            "kind": kind,
            "show": show.key,
            "show_name": show.name,
            "tier": show.tier,
            "guid": ep.guid,
            "title": ep.title,
            "url": ep.url,
            "mime": ep.mime,
            "length": ep.length,
            "seconds": ep.seconds,
            "published": ep.published.isoformat() if ep.published else None,
            "image": ep.image or art,
            "explicit": ep.explicit,
            "summary": ep.summary[:1200],
            "episode_no": self.state.meta["episode_no"],
            "airs_at": (start + timedelta(minutes=slot)).astimezone(timezone.utc).isoformat(),
            "mystery": show.has("mystery"),
        }
        self.state.airings.append(rec)
        self.log(f"  {block_id} #{slot + 1} [{kind}] {show.name}: {ep.title}")
        return rec
