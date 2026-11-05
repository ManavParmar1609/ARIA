"""The outbound draft screen reads a link's host the way a browser will."""

from __future__ import annotations

import time

import pytest

from aria.reporting.outbound import LINK_REMOVED, DraftPolicy, host_of, screen

POLICY = DraftPolicy(link_hosts=frozenset({"console.example"}))


@pytest.mark.parametrize(
    ("url", "host"),
    [
        # A browser treats "\" as "/", so the part after it is the path, not a user name.
        ("https://evil.example\\@console.example/x", "evil.example"),
        ("https://evil.example:443\\@console.example", "evil.example"),
        ("https://evil.example\\\\@console.example", "evil.example"),
        ("www.evil.example\\@console.example", "www.evil.example"),
        ("evil.example\\@console.example", "evil.example"),
        ("[](https://evil.example\\@console.example)", ""),
        # The cases that already read correctly keep reading so.
        ("https://console.example@evil.example/x", "evil.example"),
        ("https://console.example/runs/1", "console.example"),
        ("https://CONSOLE.example./runs", "console.example"),
        ("https://evil.example#@console.example", "evil.example"),
        # No browser opens a port that is not a number, so there is no host to allow.
        ("https://console.example:evil.example/x", ""),
    ],
)
def test_the_host_of_a_link_is_the_one_a_browser_opens(url: str, host: str) -> None:
    assert host_of(url) == host


@pytest.mark.parametrize(
    "text",
    [
        "Details: https://evil.example\\@console.example/runs/1 (see the report)",
        "Details: https://evil.example:443\\@console.example",
        "Details: [the report](https://evil.example\\@console.example/runs/1)",
        "Details: www.evil.example\\@console.example",
        "Details: https://console.example:evil.example/runs/1",
    ],
)
def test_a_backslash_before_the_at_sign_cannot_smuggle_a_link_past_the_allow_list(
    text: str,
) -> None:
    screened = screen(text, POLICY)
    assert "evil" not in screened.text, screened.text
    assert LINK_REMOVED in screened.text
    assert screened.removed, "the reviewer is told what was removed"
    assert all("evil.example" not in item for item in screened.removed), screened.removed


def test_an_allowed_link_still_passes_whole() -> None:
    text = "Open https://console.example/console/runs/run-1?tab=report. Then decide."
    screened = screen(text, POLICY)
    assert screened.text == text
    assert screened.removed == []


def test_markdown_links_with_titles_are_still_read_and_a_never_closed_one_costs_linear_time() -> (
    None
):
    titled = 'See [the report](https://console.example/runs/1 "the report") and [more](https://evil.example/x "x").'
    screened = screen(titled, POLICY)
    assert "https://console.example/runs/1" in screened.text
    assert "evil" not in screened.text
    assert screened.removed == ["link to evil[.]example"]
    started = time.perf_counter()
    screen("[x](" + "a" * 200_000, POLICY)
    assert time.perf_counter() - started < 3.0  # about 15 seconds before the title tail was fixed
