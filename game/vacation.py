"""Detecta modo férias da conta (advice-bar → preferences tab)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def href_is_vacation(href: str) -> bool:
    """True se o link do advice-bar aponta pro grupo férias das prefs.

    OGame legado: page=preferences&selectedTab=3&openGroup=0
    OGame atual:  page=ingame&component=preferences&selectedTab=3&openGroup=0
    """
    if not href or "preferences" not in href:
        return False
    try:
        q = parse_qs(urlparse(href).query)
    except Exception:
        return False
    page = (q.get("page") or [""])[0]
    component = (q.get("component") or [""])[0]
    tab = (q.get("selectedTab") or [""])[0]
    group = (q.get("openGroup") or [""])[0]
    prefs = page == "preferences" or component == "preferences"
    return prefs and tab == "3" and group == "0"


def is_vacation_mode(page) -> bool:
    """Paridade ogame ExtractIsInVacationFromDoc: div#advice-bar a."""
    try:
        hrefs = page.locator("div#advice-bar a").evaluate_all(
            "els => els.map(e => e.getAttribute('href') || '')"
        )
    except Exception:
        return False
    return any(href_is_vacation(h) for h in (hrefs or []))


if __name__ == "__main__":
    assert href_is_vacation(
        "https://s1-br.ogame.gameforge.com/game/index.php?"
        "page=preferences&selectedTab=3&openGroup=0"
    )
    assert href_is_vacation(
        "https://s182-br.ogame.gameforge.com/game/index.php?"
        "page=ingame&component=preferences&selectedTab=3&openGroup=0"
    )
    assert not href_is_vacation(
        "index.php?page=ingame&component=preferences&selectedTab=0&openGroup=0"
    )
    assert not href_is_vacation(
        "index.php?page=preferences&selectedTab=0&openGroup=0"
    )
    assert not href_is_vacation("")
    print("vacation ok")
