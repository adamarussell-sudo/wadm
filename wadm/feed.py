"""Writes the podcast feed and the little web page that goes with it."""
import html
from datetime import date, datetime, timedelta
from email.utils import format_datetime
from urllib.parse import quote
from xml.sax.saxutils import escape

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def slot_label(a: dict) -> str:
    d = date.fromisoformat(a["date"])
    when = "Night" if a["kind"] == "night" else ("AM" if a["block"].endswith("-am") else "PM")
    label = f"{DOW[d.weekday()]} {when}"
    if a["kind"] == "wildcard":
        label += " · Wildcard"
    return label


def vote_link(repo: str, verb: str, show: str) -> str:
    title = quote(f"{verb}: {show}")
    body = quote("Tap Submit. WADM counts this vote on its next run and closes this note.")
    return f"https://github.com/{repo}/issues/new?title={title}&body={body}"


def notes_html(a: dict, repo: str) -> str:
    parts = []
    if a.get("summary"):
        for para in a["summary"].split("\n\n")[:6]:
            parts.append(f"<p>{html.escape(para)}</p>")
    released = ""
    if a.get("published"):
        released = ", first released " + datetime.fromisoformat(a["published"]).strftime("%B %-d, %Y")
    parts.append(f"<p>From <b>{html.escape(a['show_name'])}</b>{released}.</p>")
    if a["tier"] == "wildcard":
        parts.append("<p>This one is a wildcard on trial. Two votes for More promotes it; three for Less sends it home.</p>")
    if repo:
        parts.append(
            f'<p><a href="{vote_link(repo, "more", a["show_name"])}">More like this</a> · '
            f'<a href="{vote_link(repo, "less", a["show_name"])}">Less like this</a></p>'
        )
    return "\n".join(parts)


def current_airings(state, today: date, keep_days: int):
    cut = (today - timedelta(days=keep_days - 1)).isoformat()
    items = [a for a in state.airings if a["date"] >= cut]
    return sorted(items, key=lambda a: a["episode_no"], reverse=True)


def build_feed(station: dict, state, base_url: str, repo: str, today: date, now: datetime) -> str:
    items = current_airings(state, today, int(station.get("keep_days", 4)))
    base = base_url.rstrip("/")
    cover = f"{base}/cover.jpg"
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        "<channel>",
        f"<title>{escape(station.get('name', 'WADM'))}</title>",
        f"<link>{escape(base)}/</link>",
        f'<atom:link href="{escape(base)}/feed.xml" rel="self" type="application/rss+xml"/>',
        f"<description>{escape(station.get('tagline', ''))}</description>",
        "<language>en-us</language>",
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>",
        f"<itunes:author>{escape(station.get('name', 'WADM'))}</itunes:author>",
        f"<itunes:summary>{escape(station.get('tagline', ''))}</itunes:summary>",
        f'<itunes:image href="{escape(cover)}"/>',
        f"<image><url>{escape(cover)}</url><title>{escape(station.get('name', 'WADM'))}</title><link>{escape(base)}/</link></image>",
        "<itunes:type>serial</itunes:type>",
        "<itunes:explicit>true</itunes:explicit>",
        "<itunes:block>Yes</itunes:block>",
        '<itunes:category text="Leisure"/>',
    ]
    for a in items:
        title = f"{slot_label(a)} · {a['show_name']}: {a['title']}"
        notes = notes_html(a, repo)
        pub = datetime.fromisoformat(a["airs_at"])
        out += [
            "<item>",
            f"<title>{escape(title)}</title>",
            f"<itunes:title>{escape(title)}</itunes:title>",
            f"<description>{cdata(notes)}</description>",
            f"<content:encoded>{cdata(notes)}</content:encoded>",
            f'<enclosure url="{escape(a["url"], {chr(34): "&quot;"})}" length="{int(a.get("length") or 0)}" type="{escape(a.get("mime") or "audio/mpeg")}"/>',
            f'<guid isPermaLink="false">wadm-{a["block"]}-{a["slot"]}</guid>',
            f"<pubDate>{format_datetime(pub)}</pubDate>",
            f"<itunes:episode>{a['episode_no']}</itunes:episode>",
            "<itunes:episodeType>full</itunes:episodeType>",
            f"<itunes:explicit>{'true' if a.get('explicit') else 'false'}</itunes:explicit>",
        ]
        if a.get("seconds"):
            out.append(f"<itunes:duration>{int(a['seconds'])}</itunes:duration>")
        if a.get("image"):
            out.append(f'<itunes:image href="{escape(a["image"], {chr(34): "&quot;"})}"/>')
        out.append("</item>")
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


def build_page(station: dict, state, base_url: str, today: date) -> str:
    feed_url = base_url.rstrip("/") + "/feed.xml"
    items = current_airings(state, today, 2)
    blocks = {}
    for a in sorted(items, key=lambda a: a["episode_no"]):
        blocks.setdefault(a["block"], []).append(a)
    rows = []
    for block_id in sorted(blocks, reverse=True):
        first = blocks[block_id][0]
        d = date.fromisoformat(first["date"])
        heading = f"{DOW[d.weekday()]} {d.strftime('%B %-d')} · {'morning' if block_id.endswith('-am') else 'evening'}"
        rows.append(f"<h2>{html.escape(heading)}</h2><ol>")
        for a in blocks[block_id]:
            tag = {"wildcard": "wildcard", "night": "after dark"}.get(a["kind"], a["tier"])
            rows.append(
                f'<li><span class="show">{html.escape(a["show_name"])}</span>'
                f'<span class="ep">{html.escape(a["title"])}</span>'
                f'<span class="tag">{html.escape(tag)}</span></li>'
            )
        rows.append("</ol>")
    name = html.escape(station.get("name", "WADM"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<meta name="robots" content="noindex">
<style>
:root {{ --bg:#f6f1e7; --ink:#1d1a16; --muted:#6b6255; --line:#d9cfbd; --accent:#b4421f; --on-accent:#fff; --card:#fffaf0; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#16130f; --ink:#efe6d6; --muted:#a69a87; --line:#3a332a; --accent:#e8784f; --on-accent:#1d1a16; --card:#1f1b16; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 Georgia, 'Times New Roman', serif; }}
main {{ max-width:640px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font:700 56px/1 'Arial Black', Impact, sans-serif; letter-spacing:.04em; margin:0; }}
.tag-line {{ color:var(--muted); margin:6px 0 28px; }}
.sub {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }}
.sub p {{ margin:0 0 10px; }}
.url {{ display:flex; gap:8px; }}
.url input {{ flex:1; min-width:0; font:14px ui-monospace, Menlo, monospace; padding:10px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--ink); }}
button {{ font:600 14px system-ui, sans-serif; padding:10px 14px; border:0; border-radius:8px; background:var(--accent); color:var(--on-accent); cursor:pointer; }}
h2 {{ font:600 13px system-ui, sans-serif; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:32px 0 8px; }}
ol {{ list-style:none; margin:0; padding:0; border-top:1px solid var(--line); }}
li {{ display:grid; grid-template-columns:1fr auto; gap:0 12px; padding:10px 0; border-bottom:1px solid var(--line); }}
.show {{ font-weight:700; }}
.ep {{ grid-column:1; color:var(--muted); font-size:14px; }}
.tag {{ grid-column:2; grid-row:1 / span 2; align-self:center; font:12px system-ui, sans-serif; color:var(--accent); }}
</style></head><body><main>
<h1>{name}</h1>
<p class="tag-line">{html.escape(station.get('tagline', ''))}</p>
<div class="sub">
<p>In Apple Podcasts: Library, the ··· menu, Follow a Show by URL, paste this.</p>
<div class="url"><input id="u" value="{html.escape(feed_url)}" readonly><button onclick="navigator.clipboard.writeText(document.getElementById('u').value).then(()=>{{this.textContent='Copied'}})">Copy</button></div>
</div>
{''.join(rows) or '<p>Nothing on the schedule yet.</p>'}
</main></body></html>
"""
