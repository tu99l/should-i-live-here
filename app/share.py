"""A view-only results link for roommates who aren't at this laptop.

The app runs on one laptop. To let roommates see the map on their phones, `scripts/share_link.py`
starts a free Cloudflare quick tunnel: a temporary public https address that forwards to this
laptop's app. Two protections keep that safe:
1. A secret code in the link (/share/<code>), stored in data/share.local.json (git-ignored).
2. Requests that come through the tunnel can only reach the share page and its read-only data.
   Everything else (searches, invites, edits, anything that costs API calls) answers 404 to them.
   See `allowed_from_outside` and the middleware in main.py.
"""
import json
import re
import secrets
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
SHARE_FILE = ROOT / "data" / "share.local.json"

# Files the share page itself needs (everything else under /static stays local-only).
SHARE_STATIC = {"/static/share.html", "/static/share.js", "/static/share.css"}


def _load() -> dict:
    try:
        return json.loads(SHARE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    SHARE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SHARE_FILE.write_text(json.dumps(data, indent=2))


def code() -> str:
    """The secret part of the link, made once and kept (so links already texted keep working)."""
    data = _load()
    if not data.get("code"):
        data["code"] = secrets.token_urlsafe(9)
        _save(data)
    return data["code"]


def set_public_url(url: Optional[str]) -> None:
    """Called by scripts/share_link.py when the tunnel starts (and with None when it stops)."""
    data = _load()
    data["public_url"] = url.rstrip("/") if url else None
    _save(data)


def link() -> Optional[str]:
    """The link to text roommates, or None when no tunnel is running."""
    url = _load().get("public_url")
    return f"{url}/share/{code()}" if url else None


def from_outside(host: str, headers) -> bool:
    """True for requests that came through the tunnel (or any non-local address)."""
    hostname = (host or "").split(":")[0].lower()
    # "testserver" is the test client. Tunnel traffic always has Cloudflare's header and a trycloudflare.com host.
    return bool(headers.get("cf-connecting-ip")) or hostname not in ("localhost", "127.0.0.1", "::1", "", "testserver")


def allowed_from_outside(method: str, path: str) -> bool:
    """What a request through the tunnel may reach: only the share page and its read-only data."""
    if method != "GET":
        return False
    if path in SHARE_STATIC:
        return True
    return bool(re.fullmatch(r"/share/[A-Za-z0-9_-]+|/api/share/[A-Za-z0-9_-]+", path))
