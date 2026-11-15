import json

from jkbms_widget import updates
from jkbms_widget.updates import Release, is_newer, parse_release, parse_version


def test_versions_compare_numerically():
    assert parse_version("v0.10.0") == (0, 10, 0)
    assert parse_version("1.0-beta") is None and parse_version("") is None
    assert is_newer("0.10.0", "0.9.3")  # not a text comparison
    assert is_newer("v1.0", "0.9.9")
    assert not is_newer("0.8", "0.8.0") and not is_newer("0.7.0", "0.8.0")
    assert not is_newer("junk", "0.8.0")


def release_json(**kw):
    data = {"tag_name": "v0.9.0", "html_url": "https://github.com/x/y/releases/tag/v0.9.0",
            "draft": False, "prerelease": False}
    data.update(kw)
    return json.dumps(data)


def test_latest_release_is_parsed_and_drafts_are_ignored():
    assert parse_release(release_json()) == Release(
        "0.9.0", "https://github.com/x/y/releases/tag/v0.9.0")
    assert parse_release(release_json(prerelease=True)) is None
    assert parse_release(release_json(draft=True)) is None
    assert parse_release(release_json(tag_name="nightly")) is None
    assert parse_release("not json") is None
    # Only GitHub pages are opened; anything else falls back to the releases page.
    assert parse_release(release_json(html_url="https://evil.example/")).url == updates.RELEASES_PAGE


def test_request_sends_no_personal_data():
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return release_json().encode()

    def fake_urlopen(req, timeout):
        seen["url"], seen["headers"] = req.full_url, dict(req.header_items())
        return Resp()

    import urllib.request

    orig = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        assert updates.fetch_latest().version == "0.9.0"
    finally:
        urllib.request.urlopen = orig
    assert seen["url"] == updates.LATEST_API
    assert set(seen["headers"]) == {"Accept", "User-agent"}
    assert seen["headers"]["User-agent"].startswith("bms-monitor-update-check/")
