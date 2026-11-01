"""The bouncer: reads every episode before it airs."""
import json
import re

API = "https://api.anthropic.com/v1/messages"


def hits(text: str, words) -> set:
    found = set()
    for w in words or []:
        if re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])", text):
            found.add(w.lower())
    return found


class Bouncer:
    def __init__(self, cfg: dict, state, session, api_key: str = "", log=print):
        self.cfg = cfg
        self.cache = state.bouncer
        self.session = session
        self.api_key = api_key
        self.log = log
        self.api_ok = bool(api_key)

    def judge(self, ep, now_iso: str = ""):
        """Return (air: bool, reason: str). Each episode is judged once."""
        key = f"{ep.show_key}|{ep.guid}"
        if key in self.cache:
            v = self.cache[key]
            return v["verdict"] == "air", v.get("reason", "")
        text = f"{ep.title}\n{ep.summary}".lower()
        strong = hits(text, self.cfg.get("strong_words"))
        soft = hits(text, self.cfg.get("soft_words"))

        verdict, reason, by = None, "", "keywords"
        if self.api_ok:
            try:
                verdict, reason = self._ask_claude(ep)
                by = "claude"
            except Exception as exc:
                self.log(f"  bouncer: Claude unavailable ({exc}); using keyword lists")
                self.api_ok = False
        if verdict is None:
            if strong:
                verdict, reason = "bounce", "mentions " + ", ".join(sorted(strong))
            elif len(soft) >= 2:
                verdict, reason = "bounce", "mentions " + ", ".join(sorted(soft))
            else:
                verdict, reason = "air", "clean"
        self.cache[key] = {
            "verdict": verdict,
            "reason": reason[:120],
            "by": by,
            "show": ep.show_name,
            "title": ep.title[:160],
            "at": now_iso,
        }
        if verdict == "bounce":
            self.log(f"  bounced: {ep.show_name}: {ep.title} ({reason})")
        return verdict == "air", reason

    def _ask_claude(self, ep):
        system = (
            "You screen podcast episodes for one listener's personal radio station. "
            f"His rule: {self.cfg.get('rule', '').strip()} "
            'Reply with JSON only: {"verdict": "air" or "bounce", "reason": "under ten words"}.'
        )
        user = f"Show: {ep.show_name}\nTitle: {ep.title}\nShow notes: {ep.summary[:1500]}"
        r = self.session.post(
            API,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": str(self.cfg.get("api_version", "2023-06-01")),
                "content-type": "application/json",
            },
            json={
                "model": self.cfg.get("model", "claude-haiku-5-5"),
                "max_tokens": 120,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=40,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
        verdict = str(data.get("verdict", "")).lower()
        if verdict not in ("air", "bounce"):
            raise ValueError(f"unexpected reply: {text[:80]}")
        return verdict, str(data.get("reason", ""))
