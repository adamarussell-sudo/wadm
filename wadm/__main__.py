"""WADM command line.

python -m wadm run              build the next block, write docs/feed.xml
python -m wadm run --block pm   build a specific block
python -m wadm status           roster, tiers, votes and this week's plays
"""
import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from .bouncer import Bouncer
from .config import ROOT, TIERS, load_roster, load_yaml, multiplier, slug
from .feed import build_feed, build_page
from .rotation import Programmer
from .state import State
from .votes import process_votes


def log(msg: str):
    print(msg, flush=True)


def monthly_wildcard(state, station, roster, local: datetime):
    if not station.get("monthly_wildcard", True):
        return
    month = local.strftime("%Y-%m")
    if "discovery_month" not in state.meta:
        state.meta["discovery_month"] = month  # first new wildcard arrives next month
        return
    if state.meta["discovery_month"] == month:
        return
    state.meta["discovery_month"] = month
    have = {s.key for s in roster}
    for cand in load_yaml("candidates.yaml").get("candidates") or []:
        if slug(cand["name"]) not in have:
            state.meta["added"].append(dict(cand, tier="wildcard"))
            log(f"New wildcard this month: {cand['name']}")
            return
    log("No candidates left in candidates.yaml")


def prune(state, today: date, keep_days: int):
    """Old airings only need enough to prevent repeats."""
    cut = (today - timedelta(days=keep_days + 1)).isoformat()
    for a in state.airings:
        if a["date"] < cut:
            for k in ("summary", "image", "url", "mime", "length"):
                a.pop(k, None)


def run(args):
    station = load_yaml("station.yaml")
    state = State(os.path.join(ROOT, "state"))
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    tz = ZoneInfo(station.get("timezone", "America/New_York"))
    local = now.astimezone(tz)
    block = args.block if args.block != "auto" else ("am" if local.hour < 14 else "pm")
    day = local.date()

    session = requests.Session()
    session.headers["User-Agent"] = "WADM/1.0 (personal podcast rotation)"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")

    roster = load_roster(state)
    if repo and token and owner:
        process_votes(state, roster, station, session, repo, token, owner, log)
    monthly_wildcard(state, station, roster, local)
    roster = load_roster(state)

    bouncer = Bouncer(station.get("bouncer", {}), state, session, os.environ.get("ANTHROPIC_API_KEY", ""), log)
    programmer = Programmer(station, roster, state, session, bouncer, now, log)
    # If GitHub skipped the morning run, the evening run catches it up first.
    todo = [block] if args.block != "auto" or block == "am" else ["am", "pm"]
    for b in todo:
        log(f"Building {day.isoformat()}-{b} ({'Claude' if bouncer.api_ok else 'keyword'} bouncer)")
        programmer.build(b, day)

    base_url = os.environ.get("WADM_BASE_URL") or station.get("base_url") or "https://example.github.io/wadm"
    docs = os.path.join(ROOT, "docs")
    os.makedirs(docs, exist_ok=True)
    with open(os.path.join(docs, "feed.xml"), "w", encoding="utf-8") as fh:
        fh.write(build_feed(station, state, base_url, repo, day, now))
    with open(os.path.join(docs, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(build_page(station, state, base_url, day))
    prune(state, day, int(station.get("keep_days", 4)))
    state.save()


def status(args):
    station = load_yaml("station.yaml")
    state = State(os.path.join(ROOT, "state"))
    roster = load_roster(state)
    start = (date.today() - timedelta(days=6)).isoformat()
    plays = Counter(a["show"] for a in state.airings if a["date"] >= start)
    for tier in list(TIERS) + ["retired"]:
        shows = [s for s in roster if s.tier == tier]
        if not shows:
            continue
        print(f"\n{tier.upper()}")
        for s in shows:
            mult = multiplier(s, station.get("votes", {}))
            extra = f"  votes +{s.more}/-{s.less} (x{mult:.2f})" if (s.more or s.less) else ""
            moved = f"  [was {s.base_tier}]" if s.base_tier != s.tier else ""
            print(f"  {plays[s.key]:>2} this week  {s.name}{extra}{moved}")
    bounced = [v for v in state.bouncer.values() if v["verdict"] == "bounce"]
    print(f"\nBouncer has turned away {len(bounced)} episodes.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="wadm")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--block", choices=["auto", "am", "pm"], default="auto")
    r.add_argument("--now", help="pretend it's this ISO time (testing)")
    r.set_defaults(func=run)
    s = sub.add_parser("status")
    s.set_defaults(func=status)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
