"""Update check: is there a newer release on GitHub? (step E, owner 2026-11-15)

Only reads the latest release's version number from the public GitHub
API. Nothing is downloaded or installed: the app tells the user and opens
the release page in the browser. The request carries no user data, just a
generic User-Agent with the app version. Pure Python, no Qt (unit-tested);
`fetch_latest` blocks, so the app calls it from a background thread.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

# The only place that names the repository (it may be renamed; GitHub
# redirects old names, and urllib follows the redirect).
REPO = "linux2020l/OpenBMS-Monitor"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
CHECK_EVERY_S = 24 * 3600
FIRST_CHECK_DELAY_S = 60  # after start: let the BMS connect first
TIMEOUT_S = 10


@dataclass(frozen=True)
class Release:
    version: str  # "0.8.0"
    url: str  # release page


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v0.8.0' / '0.8' -> (0, 8, 0) / (0, 8); anything else (e.g. '1.0-beta') -> None."""
    text = text.strip().lstrip("vV")
    parts = text.split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))  # 0.8 == 0.8.0
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def parse_release(data: str | bytes) -> Release | None:
    """The GitHub "latest release" JSON -> Release (None for drafts, pre-releases, junk)."""
    try:
        obj = json.loads(data)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or obj.get("draft") or obj.get("prerelease"):
        return None
    tag = obj.get("tag_name")
    if not isinstance(tag, str) or parse_version(tag) is None:
        return None
    url = obj.get("html_url")
    if not (isinstance(url, str) and url.startswith("https://github.com/")):
        url = RELEASES_PAGE
    return Release(tag.strip().lstrip("vV"), url)


def fetch_latest() -> Release | None:
    """Ask GitHub for the latest release (blocking). None on any error."""
    req = urllib.request.Request(LATEST_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"bms-monitor-update-check/{__version__}",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return parse_release(resp.read(256_000))
    except (urllib.error.URLError, OSError, ValueError):
        return None
