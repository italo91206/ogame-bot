"""Galaxy scan: fetch system + list inactive farm targets."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from playwright.sync_api import Page

from .models import Coords

_ROW_RE = re.compile(
    r'<tr[^>]*class="([^"]*\brow\b[^"]*)"[^>]*>(.*?)</tr>',
    re.I | re.S,
)
_POS_RE = re.compile(r'<td[^>]*class="[^"]*\bposition\b[^"]*"[^>]*>\s*(\d+)\s*<', re.I)
_PLANET_ID_RE = re.compile(r'data-planet-id="(\d+)"', re.I)
_NAME_RE = re.compile(r'<td[^>]*class="[^"]*\bplanetname\b[^"]*"[^>]*>(.*?)</td>', re.I | re.S)
_PLAYER_RE = re.compile(r'<td[^>]*class="[^"]*\bplayername\b[^"]*"[^>]*>(.*?)</td>', re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class GalaxyTarget:
    coords: Coords
    name: str = ""
    player: str = ""
    rank: int = 0


def _strip(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


def parse_inactive_from_html(
    html: str, galaxy: int | None = None, system: int | None = None
) -> list[GalaxyTarget]:
    """Parse galaxytable HTML (or JSON-wrapped {galaxy: html}). Planets only."""
    try:
        data = json.loads(html)
        if isinstance(data, dict) and "galaxy" in data:
            html = data["galaxy"]
    except (json.JSONDecodeError, TypeError):
        pass
    g = galaxy
    s = system
    m = re.search(r'data-galaxy="(\d+)"', html)
    if m:
        g = int(m.group(1))
    m = re.search(r'data-system="(\d+)"', html)
    if m:
        s = int(m.group(1))
    if g is None or s is None:
        return []

    out: list[GalaxyTarget] = []
    for rm in _ROW_RE.finditer(html):
        classes = rm.group(1)
        body = rm.group(2)
        if "empty_filter" in classes:
            continue
        if "inactive_filter" not in classes and "longinactive" not in classes:
            # inactive_filter is the reliable flag; also accept status spans
            if "status_abbr_inactive" not in body and "status_abbr_longinactive" not in body:
                continue
        if "vacation_filter" in classes or "status_abbr_vacation" in body:
            continue
        if "status_abbr_banned" in body or "status_abbr_admin" in body:
            continue
        pm = _POS_RE.search(body)
        if not pm:
            continue
        pos = int(pm.group(1))
        if not _PLANET_ID_RE.search(body):
            continue
        name_m = _NAME_RE.search(body)
        player_m = _PLAYER_RE.search(body)
        out.append(
            GalaxyTarget(
                coords=Coords(g, s, pos, "Planet"),
                name=_strip(name_m.group(1)) if name_m else "",
                player=_strip(player_m.group(1)) if player_m else "",
            )
        )
    return out


def parse_inactive_from_json(data: dict) -> list[GalaxyTarget]:
    """v10+ fetchGalaxyContent JSON → inactive planets (skip vacation/banned/admin)."""
    system = data.get("system") or {}
    if not system and isinstance(data.get("galaxyContent"), list):
        system = data
    g = int(system.get("galaxy") or 0)
    s = int(system.get("system") or 0)
    content = system.get("galaxyContent") or []
    out: list[GalaxyTarget] = []
    for slot in content:
        player = slot.get("player") or {}
        if not player.get("isInactive"):
            continue
        if player.get("isOnVacation") or player.get("isBanned") or player.get("isAdmin"):
            continue
        pos = int(slot.get("position") or 0)
        if pos <= 0:
            continue
        planets = slot.get("planets") or []
        if isinstance(planets, dict):
            planets = list(planets.values())
        planet = None
        for p in planets:
            if not isinstance(p, dict) or p.get("isDestroyed"):
                continue
            # 1=planet, 3=moon
            if int(p.get("planetType") or 1) == 1:
                planet = p
                break
        if planet is None and planets:
            p0 = planets[0]
            if isinstance(p0, dict) and not p0.get("isDestroyed"):
                planet = p0
        if planet is None:
            continue
        rank = 0
        rj = player.get("rank") or {}
        if isinstance(rj, dict):
            try:
                rank = int(rj.get("position") or rj.get("score") or 0)
            except (TypeError, ValueError):
                rank = 0
        else:
            try:
                rank = int(player.get("highscorePositionPlayer") or 0)
            except (TypeError, ValueError):
                rank = 0
        out.append(
            GalaxyTarget(
                coords=Coords(g, s, pos, "Planet"),
                name=str(planet.get("planetName") or ""),
                player=str(player.get("playerName") or ""),
                rank=rank,
            )
        )
    return out


def _galaxy_raw(page: Page, galaxy: int, system: int) -> tuple[dict | None, str]:
    base = page.url.split("?")[0]
    url = (
        f"{base}?page=ingame&component=galaxy"
        f"&action=fetchGalaxyContent&ajax=1&asJson=1"
    )
    resp = page.request.post(
        url,
        form={"galaxy": str(galaxy), "system": str(system)},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    text = resp.text()
    try:
        data = resp.json()
    except Exception:
        data = None
    return (data if isinstance(data, dict) else None), text


def fetch_galaxy(page: Page, galaxy: int, system: int) -> list[GalaxyTarget]:
    """POST fetchGalaxyContent; JSON first, HTML fallback."""
    data, text = _galaxy_raw(page, galaxy, system)
    if data is not None:
        targets = parse_inactive_from_json(data)
        if targets or data.get("system"):
            return targets
        if "galaxy" in data and isinstance(data["galaxy"], str):
            return parse_inactive_from_html(data["galaxy"], galaxy, system)
    return parse_inactive_from_html(text, galaxy, system)


_DEBRIS_BLOCK_RE = re.compile(
    r'id="debris(\d+)"[^>]*>(.*?)</div>\s*</div>',
    re.I | re.S,
)
_DEBRIS_RES_RE = re.compile(
    r"debris-content[^>]*>\s*(?:Metal|Metall|Métal|Metallo|Metal)\s*:\s*([\d.\s]+)",
    re.I,
)
_DEBRIS_CRY_RE = re.compile(
    r"debris-content[^>]*>\s*(?:Crystal|Kristall|Cristal|Cristallo)\s*:\s*([\d.\s]+)",
    re.I,
)
_NUM_RE = re.compile(r"[^\d]")


def _parse_res_num(raw: str) -> int:
    return int(_NUM_RE.sub("", raw) or "0")


@dataclass(frozen=True)
class DebrisField:
    coords: Coords
    metal: int = 0
    crystal: int = 0

    @property
    def total(self) -> int:
        return self.metal + self.crystal


def parse_debris_from_html(
    html: str, galaxy: int, system: int
) -> list[DebrisField]:
    out: list[DebrisField] = []
    for m in _DEBRIS_BLOCK_RE.finditer(html):
        pos = int(m.group(1))
        body = m.group(2)
        mm = _DEBRIS_RES_RE.search(body)
        cm = _DEBRIS_CRY_RE.search(body)
        metal = _parse_res_num(mm.group(1)) if mm else 0
        crystal = _parse_res_num(cm.group(1)) if cm else 0
        if metal + crystal <= 0:
            continue
        out.append(
            DebrisField(Coords(galaxy, system, pos, "Debris"), metal, crystal)
        )
    return out


def parse_empty_positions_from_json(
    data: dict, galaxy: int | None = None, system: int | None = None
) -> list[Coords]:
    """Slots 1..15 sem planeta (colonizar)."""
    sys = data.get("system") or {}
    if not isinstance(sys, dict):
        sys = {}
    if not sys and isinstance(data.get("galaxyContent"), list):
        sys = data
    # prefer fetch args — API pode mandar "0" (truthy) e matar `json or arg`
    g = int(galaxy or sys.get("galaxy") or 0)
    s = int(system or sys.get("system") or 0)
    if g <= 0 or s <= 0:
        return []
    content = sys.get("galaxyContent") or []
    occupied: set[int] = set()
    for slot in content:
        pos = int(slot.get("position") or 0)
        planets = slot.get("planets") or []
        if isinstance(planets, dict):
            planets = list(planets.values())
        for p in planets:
            if isinstance(p, dict) and not p.get("isDestroyed"):
                if int(p.get("planetType") or 1) == 1:
                    occupied.add(pos)
                    break
        player = slot.get("player") or {}
        if player and pos:
            occupied.add(pos)
    return [Coords(g, s, p, "Planet") for p in range(1, 16) if p not in occupied]


def clamp_system(system: int, n_systems: int = 499) -> int:
    n = max(1, int(n_systems))
    return ((int(system) - 1) % n) + 1


def fetch_debris_near(
    page: Page, galaxy: int, system: int, *, radius: int = 5, n_systems: int = 499
) -> list[DebrisField]:
    found: list[DebrisField] = []
    for ds in range(system - radius, system + radius + 1):
        sys = clamp_system(ds, n_systems)
        data, text = _galaxy_raw(page, galaxy, sys)
        html = text
        if data and isinstance(data.get("galaxy"), str):
            html = data["galaxy"]
        found.extend(parse_debris_from_html(html, galaxy, sys))
    return found


def fetch_empty_system(page: Page, galaxy: int, system: int) -> list[Coords]:
    data, _text = _galaxy_raw(page, galaxy, system)
    if data is None:
        return []
    # sempre carimbar g/s do request (JSON do jogo manda 0/"0" às vezes)
    return [
        Coords(int(galaxy), int(system), c.position, "Planet")
        for c in parse_empty_positions_from_json(data, galaxy, system)
        if c.position > 0
    ]


def fetch_empty_near(
    page: Page, galaxy: int, system: int, *, radius: int = 5, n_systems: int = 499
) -> list[Coords]:
    found: list[Coords] = []
    for ds in range(system - radius, system + radius + 1):
        sys = clamp_system(ds, n_systems)
        found.extend(fetch_empty_system(page, galaxy, sys))
    return found


def ogame_distance(a: Coords, b: Coords) -> int:
    """TBot-ish distance units (good enough for closest-origin pick)."""
    if a.galaxy != b.galaxy:
        return abs(a.galaxy - b.galaxy) * 20_000
    if a.system != b.system:
        d = abs(a.system - b.system)
        return d * 95 + 2700
    if a.position != b.position:
        return abs(a.position - b.position) * 5 + 1000
    return 5


if __name__ == "__main__":
    from pathlib import Path

    sample = Path(
        r"C:\Users\italo\Desktop\TBot\ogame\samples\unversioned\galaxy_inactive_emperor.html"
    )
    if sample.exists():
        html = sample.read_text(encoding="utf-8", errors="replace")
        found = parse_inactive_from_html(html)
        assert found, "expected inactive planets in sample"
        assert all(t.coords.type == "Planet" for t in found)
        print(f"galaxy html ok: {len(found)} inativos", found[0].coords)
    js = {
        "system": {
            "galaxy": 2,
            "system": 100,
            "galaxyContent": [
                {
                    "position": 8,
                    "player": {
                        "playerName": "Idle",
                        "isInactive": True,
                        "isOnVacation": False,
                        "isBanned": False,
                        "isAdmin": False,
                        "highscorePositionPlayer": 900,
                    },
                    "planets": [
                        {
                            "planetId": 1,
                            "planetName": "Home",
                            "planetType": 1,
                            "isDestroyed": False,
                        }
                    ],
                },
                {
                    "position": 9,
                    "player": {"playerName": "Vac", "isInactive": True, "isOnVacation": True},
                    "planets": [{"planetId": 2, "planetType": 1, "isDestroyed": False}],
                },
            ],
        }
    }
    jfound = parse_inactive_from_json(js)
    assert len(jfound) == 1 and jfound[0].coords.position == 8
    empty_no_gs = {"galaxyContent": [{"position": 8, "player": {"x": 1}, "planets": [{"planetType": 1}]}]}
    assert parse_empty_positions_from_json(empty_no_gs) == []
    empties = parse_empty_positions_from_json(empty_no_gs, 1, 77)
    assert all(c.galaxy == 1 and c.system == 77 for c in empties)
    assert 8 not in {c.position for c in empties} and 12 in {c.position for c in empties}
    # API "0" truthy não pode ganhar do arg
    zeroed = {
        "system": {
            "galaxy": "0",
            "system": "0",
            "galaxyContent": [{"position": 9, "player": {"x": 1}, "planets": [{"planetType": 1}]}],
        }
    }
    z = parse_empty_positions_from_json(zeroed, 1, 55)
    assert all(c.galaxy == 1 and c.system == 55 for c in z) and 9 not in {c.position for c in z}
    assert ogame_distance(Coords(1, 1, 1), Coords(1, 2, 1)) > 0
    debris_sample = Path(
        r"C:\Users\italo\Desktop\TBot\ogame\samples\v7\galaxy_debris16.html"
    )
    if debris_sample.exists():
        raw = json.loads(debris_sample.read_text(encoding="utf-8", errors="replace"))
        dfs = parse_debris_from_html(raw["galaxy"], 1, 452)
        assert any(d.coords.position == 16 and d.total > 0 for d in dfs), dfs
    assert clamp_system(0) == 499 or clamp_system(500) == 1
    print("galaxy ok")
