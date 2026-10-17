"""Small on-disk cache for paid API replies (Gemini, Google Maps).

Each reply is saved as one JSON file under cache/<kind>/, named by a hash of its input.
The same input never costs a second call, and the demo works with no network.
"""
import hashlib
import json
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


def _path(kind: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / kind / f"{digest}.json"


def get(kind: str, key: str) -> Any | None:
    path = _path(kind, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None  # A broken cache file is treated as a miss, never as data.


def put(kind: str, key: str, value: Any) -> None:
    path = _path(kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))
