"""Runs a simulated week of WADM against fake feeds and checks the rules.

python tests/test_week.py          prints the week's schedule and the checks
"""
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

WORK = tempfile.mkdtemp(prefix="wadm-test-")
for f in ("shows.yaml", "station.yaml", "candidates.yaml"):
    shutil.copy(os.path.join(REPO, f), WORK)
os.environ["WADM_ROOT"] = WORK
os.environ["WADM_FIXTURE_DIR"] = os.path.join(WORK, "fixtures")
for k in ("GITHUB_REPOSITORY", "GITHUB_TOKEN", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)
os.environ["GITHUB_REPOSITORY"] = ""  # no vote links in the offline feed

import feedparser  # noqa: E402
import make_fixtures  # noqa: E402
from wadm.__main__ import main  # noqa: E402
from wadm.config import load_roster, load_yaml  # noqa: E402
from wadm.rotation import series_title  # noqa: E402
from wadm.state import State  # noqa: E402
from wadm.votes import apply_vote  # noqa: E402

make_fixtures.main(os.path.join(WORK, "fixtures"))
failures = []


def check(ok, label):
    print(("  ok    " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def run_day(d: date, quiet=True):
    for hh in (10, 21):
        now = datetime(d.year, d.month, d.day, hh, 15, tzinfo=timezone.utc).isoformat()
        if quiet:
            devnull = open(os.devnull, "w")
            old, sys.stdout = sys.stdout, devnull
            try:
                main(["run", "--now", now])
            finally:
                sys.stdout = old
        else:
            main(["run", "--now", now])


week = [date(2026, 11, 2) + timedelta(days=i) for i in range(7)]
for d in week:
    run_day(d)

state = State(os.path.join(WORK, "state"))
station = load_yaml("station.yaml")
roster = {s.key: s for s in load_roster(state)}
air = state.airings

# ---- the schedule ---------------------------------------------------------
print("\nWADM, simulated week of Nov 2, 2026\n")
for block in sorted({a["block"] for a in air}):
    rows = [a for a in air if a["block"] == block]
    d = date.fromisoformat(rows[0]["date"])
    print(f"{d.strftime('%a %b %-d')} {'morning' if block.endswith('am') else 'evening'}")
    for a in rows:
        tag = {"wildcard": "wildcard", "night": "after dark"}.get(a["kind"], a["tier"])
        print(f"   {a['slot'] + 1}. {a['show_name']:<45} {tag}")

print("\nChecks")
check(len(air) == 70, f"70 episodes scheduled (got {len(air)})")

by_block = defaultdict(list)
for a in air:
    by_block[a["block"]].append(a)
check(all(len({a['show'] for a in rows}) == len(rows) for rows in by_block.values()), "no show plays twice in one block")

night_only = {k for k, s in roster.items() if s.has("night_only")}
check(all(a["kind"] == "night" for a in air if a["show"] in night_only), "Mystery Theater and Coast to Coast only air after dark")

pm_ok = True
for b, rows in by_block.items():
    if b.endswith("pm"):
        tags = [roster[a["show"]] for a in rows[-2:]]
        pm_ok &= tags[0].has("mystery") and tags[1].has("night")
check(pm_ok, "every evening ends with Mystery Theater, then a late-night show")

def story_repeats(airings):
    stories = {series_title(t) for t in make_fixtures.MYSTERY}
    heard = [series_title(a["title"]) for a in airings if a.get("mystery") and series_title(a["title"]) in stories]
    return heard, len(heard) - len(set(heard))


heard, dupes = story_repeats(air)
check(dupes == 0, f"no Mystery Theater story airs twice across both CBS feeds ({len(heard)} shared stories aired)")

caps = {t: v["max_per_week"] for t, v in station["tiers"].items()}
day_counts = Counter(a["show"] for a in air if a["kind"] in ("day", "wildcard"))
over = [(roster[k].name, n) for k, n in day_counts.items() if n > caps[roster[k].tier]]
check(not over, f"weekly caps hold (love 4, fine 2, noise 1, wildcard 3){'; over: ' + str(over) if over else ''}")

mw = day_counts.get("modern-wisdom", 0)
check(mw <= 2, f"Modern Wisdom posts daily but airs at most twice ({mw})")

wild = sum(1 for a in air if a["kind"] == "wildcard")
daytime = sum(1 for a in air if a["kind"] in ("day", "wildcard"))
check(9 <= wild <= 13, f"wildcards fill about every fifth daytime slot ({wild} of {daytime})")

bad_titles = set(make_fixtures.POLITICAL.values())
check(not any(a["title"] in bad_titles for a in air), "bounced political episodes never air")
bounced = [v for v in state.bouncer.values() if v["verdict"] == "bounce"]
check(len(bounced) >= 1, f"bouncer turned away {len(bounced)} episode(s): " + "; ".join(v["title"] for v in bounced))

check(not any(a["title"].startswith(("Introducing", "Deeper")) for a in air), "trailers and 2-minute teasers are skipped")
check("hit-parade" not in {a["show"] for a in air}, "a show with a dead feed is skipped without breaking the block")

guids = [a["guid"] for a in air]
check(len(guids) == len(set(guids)), "no episode repeats within the week")

ew = [a for a in air if a["show"] == "everyday-woodworking"]
check(all("archive" in a["title"] for a in ew), f"Everyday Woodworking plays from its archive ({len(ew)} plays)")

tiers = Counter(roster[a["show"]].tier for a in air if a["kind"] == "day")
print(f"\n  daytime rotation share: {dict(tiers)}")
check(tiers["love"] > tiers["fine"] > tiers["noise"], "Love outplays Fine, Fine outplays Noise")

# ---- re-running a block changes nothing ------------------------------------
before = len(air)
run_day(week[-1])
check(len(State(os.path.join(WORK, "state")).airings) == before, "re-running a block that already aired adds nothing")

# ---- the feed --------------------------------------------------------------
xml = open(os.path.join(WORK, "docs", "feed.xml"), encoding="utf-8").read()
parsed = feedparser.parse(xml)
check(not parsed.bozo, "feed.xml is valid XML")
check(len(parsed.entries) == 40, f"feed holds the last 4 days, 40 episodes ({len(parsed.entries)})")
check(all(e.get("enclosures") for e in parsed.entries), "every feed item has audio")
check("<itunes:block>Yes</itunes:block>" in xml, "feed is kept out of Apple's public directory")
nums = [int(e.get("itunes_episode", 0)) for e in parsed.entries]
check(nums == sorted(nums, reverse=True) and len(set(nums)) == len(nums), "episode numbers run in airing order")
print("\n  newest feed titles:")
for e in parsed.entries[:5]:
    print("   ", e.title)

# ---- votes -----------------------------------------------------------------
st = State(os.path.join(WORK, "state"))
r = load_roster(st)
apply_vote(st, r, station, "more", "Strong Songs")
r = load_roster(st)
msg = apply_vote(st, r, station, "more", "Strong Songs")
check(st.overrides["strong-songs"]["tier"] == "fine", "two More votes promote a wildcard: " + msg)
for _ in range(3):
    msg = apply_vote(st, load_roster(st), station, "less", "Overdue")
check(st.overrides["overdue"]["tier"] == "retired", "three Less votes retire a wildcard: " + msg)
msg = apply_vote(st, load_roster(st), station, "ditch", "modern wisdom")
check(st.overrides["modern-wisdom"]["tier"] == "retired", "Ditch takes any show off the air: " + msg)
msg = apply_vote(st, load_roster(st), station, "more", "Planet Money")
check("1 more" in msg, "More on a regular show nudges its weight: " + msg)
st.save()

# ---- next month brings a new wildcard --------------------------------------
for d in (date(2026, 11, 30), date(2026, 12, 1)):
    run_day(d)
st = State(os.path.join(WORK, "state"))
added = [a["name"] for a in st.meta["added"]]
check(added == ["A History of Rock Music in 500 Songs"], f"December's new wildcard joins the pool: {added}")
late = [a for a in st.airings if a["date"] >= "2026-11-30"]
check(not any(a["show"] in ("modern-wisdom", "overdue") for a in late), "ditched and retired shows stay off the air")

# ---- two months on the air -------------------------------------------------
d = date(2026, 12, 2)
while d <= date(2026, 12, 31):
    run_day(d)
    d += timedelta(days=1)
st = State(os.path.join(WORK, "state"))
heard, dupes = story_repeats(st.airings)
check(dupes == 0, f"two months in, still no repeated Mystery Theater story ({len(heard)} shared stories aired, {sum(1 for a in st.airings if a.get('mystery'))} nights)")
pairs = Counter((a["show"], a["guid"]) for a in st.airings)
repeats = [k for k, n in pairs.items() if n > 1]
check(not repeats, f"no episode repeats in two months ({len(st.airings)} plays)")
check(len(st.airings) == 70 + 4 * 5 + 30 * 10, f"every block filled for two months ({len(st.airings)} plays)")

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED'}  (work dir {WORK})")
sys.exit(1 if failures else 0)
