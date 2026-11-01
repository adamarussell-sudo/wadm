"""Finding each show's feed and reading its episodes."""
import difflib
import html
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import feedparser

LOOKUP = "https://itunes.apple.com/lookup"
SEARCH = "https://itunes.apple.com/search"
RECHECK_DAYS = 30
UA = "WADM/1.0 (personal podcast rotation)"


def similar(a: str, b: str) -> float:
    a2 = " ".join(re.sub(r"[^a-z0-9 ]+", " ", (a or "").lower()).split())
    b2 = " ".join(re.sub(r"[^a-z0-9 ]+", " ", (b or "").lower()).split())
    if not a2 or not b2:
        return 0.0
    if a2 == b2:
        return 1.0
    if f" {a2} " in f" {b2} " or f" {b2} " in f" {a2} ":  # whole words only: "Lore" isn't "Folklore"
        return 0.9
    return difflib.SequenceMatcher(None, a2, b2).ratio()


def resolve(show, state, session, now: datetime, log) -> Optional[dict]:
    """Return {'feed', 'name', 'art'} for a show, from cache, shows.yaml or Apple."""
    fixtures = os.environ.get("WADM_FIXTURE_DIR")
    if fixtures:
        path = os.path.join(fixtures, f"{show.key}.xml")
        return {"feed": path, "name": show.name, "art": None} if os.path.exists(path) else None

    cached = state.resolved.get(show.key)
    if show.feed:
        info = {"feed": show.feed, "name": show.name, "art": (cached or {}).get("art")}
        state.resolved[show.key] = dict(info, checked=now.isoformat())
        return info
    if cached and cached.get("feed"):
        try:
            age = (now - datetime.fromisoformat(cached["checked"])).days
        except (KeyError, ValueError):
            age = RECHECK_DAYS
        if age < RECHECK_DAYS:
            return cached

    found = None
    try:
        if show.apple_id:
            r = session.get(LOOKUP, params={"id": show.apple_id}, timeout=20)
            r.raise_for_status()
            for res in r.json().get("results", []):
                if res.get("feedUrl") and similar(show.name, res.get("collectionName", "")) >= 0.6:
                    found = res
                    break
        if not found:
            r = session.get(SEARCH, params={"term": show.name, "media": "podcast", "entity": "podcast", "limit": 10}, timeout=20)
            r.raise_for_status()
            best, score = None, 0.0
            for res in r.json().get("results", []):
                s = similar(show.name, res.get("collectionName", ""))
                if res.get("feedUrl") and s > score:
                    best, score = res, s
            if best and score >= 0.75:
                found = best
    except Exception as exc:  # network trouble: keep whatever we had
        log(f"  lookup failed for {show.name}: {exc}")
        return cached if cached and cached.get("feed") else None

    if not found:
        log(f"  could not find a feed for {show.name}")
        return cached if cached and cached.get("feed") else None
    info = {
        "feed": found["feedUrl"],
        "name": found.get("collectionName", show.name),
        "artist": found.get("artistName"),
        "apple_id": found.get("collectionId"),
        "art": found.get("artworkUrl600"),
        "checked": now.isoformat(),
    }
    if not cached or cached.get("feed") != info["feed"]:
        log(f"  {show.name} -> {info['name']} ({info['feed']})")
    state.resolved[show.key] = info
    return info


@dataclass
class Episode:
    show_key: str
    show_name: str
    guid: str
    title: str
    published: Optional[datetime]
    url: str
    mime: str
    length: int
    seconds: Optional[int]
    summary: str
    image: Optional[str]
    explicit: bool
    kind: str


def seconds_of(value) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if ":" in text:
            total = 0
            for part in text.split(":"):
                total = total * 60 + int(float(part or 0))
            return total
        return int(float(text))
    except ValueError:
        return None


def plain(text: str) -> str:
    text = re.sub(r"<(br|/p|/div|/li)[^>]*>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def fetch(show, info: dict, session, log):
    """Download and parse a show's feed. Returns (episodes, channel_art)."""
    src = info["feed"]
    try:
        if os.path.exists(src):
            with open(src, "rb") as fh:
                body = fh.read()
        else:
            r = session.get(src, timeout=45, headers={"User-Agent": UA})
            r.raise_for_status()
            body = r.content
    except Exception as exc:
        log(f"  could not download {show.name}: {exc}")
        return [], None
    parsed = feedparser.parse(body)
    channel_art = None
    img = parsed.feed.get("image") or {}
    channel_art = img.get("href") or img.get("url") or info.get("art")

    episodes = []
    for e in parsed.entries:
        enc = None
        for link in e.get("enclosures", []) + [l for l in e.get("links", []) if l.get("rel") == "enclosure"]:
            href = link.get("href") or link.get("url")
            if href and (str(link.get("type", "")).startswith("audio") or href.split("?")[0].lower().endswith((".mp3", ".m4a", ".aac"))):
                enc = link
                break
        if not enc:
            continue
        url = enc.get("href") or enc.get("url")
        published = None
        if e.get("published_parsed"):
            published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        try:
            length = int(enc.get("length") or 0)
        except ValueError:
            length = 0
        image = None
        if isinstance(e.get("image"), dict):
            image = e["image"].get("href")
        explicit = str(e.get("itunes_explicit", "")).lower() in ("yes", "true", "explicit")
        episodes.append(Episode(
            show_key=show.key,
            show_name=show.name,
            guid=str(e.get("id") or url),
            title=plain(e.get("title", "Untitled")),
            published=published,
            url=url,
            mime=enc.get("type") or "audio/mpeg",
            length=length,
            seconds=seconds_of(e.get("itunes_duration")),
            summary=plain(e.get("summary") or e.get("description") or ""),
            image=image or channel_art,
            explicit=explicit,
            kind=str(e.get("itunes_episodetype", "full")).lower(),
        ))
    return episodes, channel_art
