"""Reads the More / Less votes Adam taps in the show notes (they arrive as GitHub issues)."""
import re

from .config import slug
from .sources import similar

PATTERN = re.compile(r"^\s*(more|less|ditch)\s*:\s*(.+?)\s*$", re.I)


def apply_vote(state, roster, station, verb: str, name: str) -> str:
    """Apply one vote. Returns the reply to post on the issue."""
    by_key = {s.key: s for s in roster}
    show = by_key.get(slug(name))
    if not show:
        scored = sorted(((similar(name, s.name), s) for s in roster), key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] >= 0.75:
            show = scored[0][1]
    if not show:
        return f"WADM doesn't have a show called '{name}'. No change."
    vcfg = station.get("votes", {})
    ov = state.overrides.setdefault(show.key, {})
    if verb == "ditch":
        ov["tier"] = "retired"
        return f"{show.name} is off the air for good."
    ov[verb] = int(ov.get(verb, 0)) + 1
    more, less = int(ov.get("more", 0)), int(ov.get("less", 0))
    if show.tier == "wildcard":
        if verb == "more" and more >= int(vcfg.get("promote_wildcard_after_more", 2)):
            ov["tier"] = "fine"
            return f"{show.name} made the cut. It's in the regular rotation now (Fine tier)."
        if verb == "less" and less >= int(vcfg.get("retire_wildcard_after_less", 3)):
            ov["tier"] = "retired"
            return f"{show.name} got three strikes. It's off the station."
    return f"Counted. {show.name} now has {more} more and {less} less."


def process_votes(state, roster, station, session, repo: str, token: str, owner: str, log=print) -> int:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}/issues"
    try:
        r = session.get(api, params={"state": "open", "creator": owner, "per_page": 100}, headers=headers, timeout=20)
        r.raise_for_status()
    except Exception as exc:
        log(f"  could not read votes: {exc}")
        return 0
    count = 0
    for issue in r.json():
        if "pull_request" in issue:
            continue
        m = PATTERN.match(issue.get("title", ""))
        if not m:
            continue
        reply = apply_vote(state, roster, station, m.group(1).lower(), m.group(2))
        log(f"  vote: {issue['title']} -> {reply}")
        count += 1
        try:
            session.post(f"{api}/{issue['number']}/comments", json={"body": reply}, headers=headers, timeout=20)
            session.patch(f"{api}/{issue['number']}", json={"state": "closed"}, headers=headers, timeout=20)
        except Exception as exc:
            log(f"  could not close vote #{issue['number']}: {exc}")
    return count
