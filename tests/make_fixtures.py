"""Builds fake podcast feeds for every show, so the station can be tested offline.

Each feed has a three-year archive plus traps the station must handle:
promos and trailers, political episodes for the bouncer, the same Mystery
Theater story in both CBS feeds, a dead feed, and very chatty publishers.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from wadm.config import slug  # noqa: E402

START = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
MYSTERY = [
    "The Old Ones Are Hard to Kill", "The Return of the Moresbys", "The Ring of Truth",
    "Lost Dog", "No Hiding Place", "The Resident", "Mother Love", "Death Rides a Stallion",
    "The Ghost Party", "Accounts Receivable", "The Bullet", "Here Is a Murder",
]
POLITICAL = {
    "freakonomics-radio": "The Midterm Election Math Nobody Talks About",
    "planet-money": "Why Congress and the Senate Fight Over Immigration Politics",
    "modern-wisdom": "Is the Culture War Over?",
}
DAILY = {"modern-wisdom", "the-diary-of-a-ceo-with-steven-bartlett", "the-journal", "wsj-your-money-briefing"}
TWICE_WEEKLY = {"the-best-of-car-talk", "smartless", "conan-o-brien-needs-a-friend", "planet-money"}
DEAD = {"hit-parade"}           # lookup fails: no fixture
STALE = {"everyday-woodworking"}  # nothing since 2024


def item(key, n, title, published, minutes=45, kind="full", desc=None):
    return (
        "<item>"
        f"<title>{escape(title)}</title>"
        f"<guid isPermaLink=\"false\">{key}-{n}</guid>"
        f"<pubDate>{format_datetime(published)}</pubDate>"
        f"<description>{escape(desc or f'Episode {n} of the fake {key} feed.')}</description>"
        f'<enclosure url="https://example.com/{key}/{n}.mp3" length="{minutes * 960000}" type="audio/mpeg"/>'
        f"<itunes:duration>{minutes * 60}</itunes:duration>"
        f"<itunes:episodeType>{kind}</itunes:episodeType>"
        "</item>"
    )


def feed(key, name):
    items, n = [], 0
    if key in STALE:
        archive_end = datetime(2024, 7, 23, tzinfo=timezone.utc)
    else:
        archive_end = START - timedelta(days=14)
    for i in range(40):  # archive: one every ~4 weeks going back
        n += 1
        title = f"{name} archive #{n}"
        if key == "cbs-radio-mystery-theater":
            title = f"CBSRMT 74-01-{i + 6:02d} e{i + 1:04d} {MYSTERY[i % len(MYSTERY)]}" if i < len(MYSTERY) else title
        if key == "cbs-radio-mystery-theater-old-time-radio":
            title = MYSTERY[i % len(MYSTERY)].title() if i < len(MYSTERY) else title
        items.append(item(key, n, title, archive_end - timedelta(days=27 * i)))
    if key not in STALE:
        step = 1 if key in DAILY else (3 if key in TWICE_WEEKLY else 7)
        d = START - timedelta(days=6)
        while d < START + timedelta(days=8):
            n += 1
            items.append(item(key, n, f"{name} new #{n}", d))
            d += timedelta(days=step)
        n += 1
        items.append(item(key, n, f"Introducing {name} Plus", START - timedelta(days=1), minutes=3, kind="trailer"))
        n += 1
        items.append(item(key, n, f"Deeper {name}: three old favorites", START - timedelta(days=2), minutes=2))
    if key in POLITICAL:
        n += 1
        items.append(item(key, n, POLITICAL[key], START - timedelta(hours=6),
                          desc="Partisan fights, election polling and what Democrats and Republicans get wrong."))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>'
        f"<title>{escape(name)}</title><image><url>https://example.com/{key}.jpg</url></image>"
        + "".join(items) + "</channel></rss>"
    )


def main(out):
    os.makedirs(out, exist_ok=True)
    names = [s["name"] for s in yaml.safe_load(open(os.path.join(ROOT, "shows.yaml")))["shows"]]
    names += [c["name"] for c in yaml.safe_load(open(os.path.join(ROOT, "candidates.yaml")))["candidates"]]
    for name in names:
        key = slug(name)
        if key in DEAD:
            continue
        with open(os.path.join(out, f"{key}.xml"), "w", encoding="utf-8") as fh:
            fh.write(feed(key, name))
    return len(names)


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fixtures")), "feeds")
