"""Building / research / LF queue countdowns."""
from __future__ import annotations

import re

from playwright.sync_api import Page

_RE_BUILD_V9 = re.compile(r"var restTimebuilding\s*=\s*(\d+)\s*-")
_RE_BUILD_V11 = re.compile(r"new CountdownTimer\('buildingCountdown',\s*(\d+)")
_RE_CANCEL_BUILD = re.compile(r"cancelbuilding\((\d+)\s*,")
_RE_RESEARCH_V9 = re.compile(r"var restTimeresearch\s*=\s*(\d+)\s*-")
_RE_RESEARCH_V11 = re.compile(r"new CountdownTimer\('researchCountdown',\s*(\d+)")
_RE_CANCEL_RESEARCH = re.compile(r"cancelresearch\((\d+)\s*,")
_RE_LFBUILD_V9 = re.compile(r"var restTimelfbuilding\s*=\s*(\d+)\s*-")
_RE_LFBUILD_V11 = re.compile(r"new CountdownTimer\('lfbuildingCountdown',\s*(\d+)")
_RE_CANCEL_LFBUILD = re.compile(r"cancellfbuilding\((\d+)\s*,")
_RE_LFRESEARCH_V9 = re.compile(r"var restTimelfresearch\s*=\s*(\d+)\s*-")
_RE_LFRESEARCH_V11 = re.compile(r"new CountdownTimer\('lfResearchCountdown',\s*(\d+)")
_RE_CANCEL_LFRESEARCH = re.compile(r"cancellfresearch\((\d+)\s*,")


def _page_html_now(page: Page) -> tuple[str, int]:
    html, now = page.evaluate(
        """() => [
          document.documentElement.innerHTML,
          Math.floor(
            (Date.now() + (window.timeDiff || 0)
             + ((window.timeZoneDiffSeconds || 0) * 1000)) / 1000
          ),
        ]"""
    )
    return html or "", int(now or 0)


def _parse_queue(
    html: str,
    now_unix: int,
    re_v9: re.Pattern[str],
    re_v11: re.Pattern[str],
    re_cancel: re.Pattern[str],
) -> tuple[int, int]:
    m1 = re_v9.search(html)
    if m1:
        cd = max(0, int(m1.group(1)) - now_unix)
        c = re_cancel.search(html)
        return (int(c.group(1)) if c else 1), cd
    m2 = re_v11.search(html)
    if m2:
        c = re_cancel.search(html)
        return (int(c.group(1)) if c else 1), max(0, int(m2.group(1)))
    return 0, 0


def parse_building_queue(html: str, now_unix: int) -> tuple[int, int]:
    """(building_id, secs). (0, 0) = idle. TBot ExtractConstructions v9/v11."""
    return _parse_queue(html, now_unix, _RE_BUILD_V9, _RE_BUILD_V11, _RE_CANCEL_BUILD)


def parse_research_queue(html: str, now_unix: int) -> tuple[int, int]:
    """(research_id, secs). (0, 0) = idle."""
    return _parse_queue(
        html, now_unix, _RE_RESEARCH_V9, _RE_RESEARCH_V11, _RE_CANCEL_RESEARCH
    )


def parse_lf_building_queue(html: str, now_unix: int) -> tuple[int, int]:
    """(lf_building_id, secs). (0, 0) = idle."""
    return _parse_queue(
        html, now_unix, _RE_LFBUILD_V9, _RE_LFBUILD_V11, _RE_CANCEL_LFBUILD
    )


def parse_lf_research_queue(html: str, now_unix: int) -> tuple[int, int]:
    """(lf_research_id, secs). (0, 0) = idle."""
    return _parse_queue(
        html, now_unix, _RE_LFRESEARCH_V9, _RE_LFRESEARCH_V11, _RE_CANCEL_LFRESEARCH
    )


def building_queue(page: Page) -> tuple[int, int]:
    """(building_id, secs) from live page. (0, 0) = idle."""
    try:
        return parse_building_queue(*_page_html_now(page))
    except Exception:
        return 0, 0


def research_queue(page: Page) -> tuple[int, int]:
    """(research_id, secs) from live page. (0, 0) = idle."""
    try:
        return parse_research_queue(*_page_html_now(page))
    except Exception:
        return 0, 0


def lf_building_queue(page: Page) -> tuple[int, int]:
    """(lf_building_id, secs) from live page. (0, 0) = idle."""
    try:
        return parse_lf_building_queue(*_page_html_now(page))
    except Exception:
        return 0, 0


def lf_research_queue(page: Page) -> tuple[int, int]:
    """(lf_research_id, secs) from live page. (0, 0) = idle."""
    try:
        return parse_lf_research_queue(*_page_html_now(page))
    except Exception:
        return 0, 0


def construction_busy(page: Page) -> bool:
    """True iff building timer still on page (TBot: BuildingID != 0)."""
    return building_queue(page)[0] != 0


def building_countdown(page: Page) -> int:
    """Seconds left on building queue; 0 if idle/unknown."""
    return building_queue(page)[1]


def research_countdown(page: Page) -> int:
    """Seconds left on research queue; 0 if idle/unknown."""
    return research_queue(page)[1]


def lf_building_countdown(page: Page) -> int:
    """Seconds left on LF building queue; 0 if idle/unknown."""
    return lf_building_queue(page)[1]


def lf_research_countdown(page: Page) -> int:
    """Seconds left on LF research queue; 0 if idle/unknown."""
    return lf_research_queue(page)[1]


if __name__ == "__main__":
    assert parse_lf_building_queue(
        "var restTimelfbuilding = 1700000100 -; cancellfbuilding(11101,",
        1700000000,
    ) == (11101, 100)
    assert parse_lf_building_queue(
        "new CountdownTimer('lfbuildingCountdown', 42,); cancellfbuilding(12102,",
        0,
    ) == (12102, 42)
    assert parse_lf_research_queue(
        "var restTimelfresearch = 1700000050 -; cancellfresearch(11201,",
        1700000000,
    )[0] == 11201
    assert parse_building_queue(
        "var restTimebuilding = 1700000100 -; cancelbuilding(1,",
        1700000000,
    ) == (1, 100)
    print("queues ok")
