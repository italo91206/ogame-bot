"""Hostile eventList parse (TBot GetAttacks)."""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from html import unescape

from playwright.sync_api import Page

from .models import Coords

MISSION_ATTACK = 1
MISSION_ACS = 2
MISSION_SPY = 6
MISSION_DESTROY = 9
MISSION_MISSILE = 10
_HOSTILE_MISSIONS = frozenset(
    {MISSION_ATTACK, MISSION_ACS, MISSION_SPY, MISSION_DESTROY, MISSION_MISSILE}
)

# TBot Ships.GetFleetPoints weights (by tech id)
_FLEET_POINTS = {
    202: 4,
    203: 12,
    204: 4,
    205: 10,
    206: 29,
    207: 60,
    208: 40,
    209: 18,
    210: 1,
    211: 90,
    213: 125,
    214: 10_000,
    215: 85,
    218: 160,
    219: 31,
}
# EN+PT labels → id (NFD accents stripped, non-alnum gone)
_SHIP_NAME_ID = {
    "smallcargo": 202,
    "cargueiropequeno": 202,
    "largecargo": 203,
    "cargueirogrande": 203,
    "lightfighter": 204,
    "cacaligeiro": 204,
    "heavyfighter": 205,
    "cacapesado": 205,
    "cruiser": 206,
    "cruzador": 206,
    "battleship": 207,
    "navedebatalha": 207,
    "colonyship": 208,
    "navedecolonizacao": 208,
    "navecolonizadora": 208,
    "recycler": 209,
    "reciclador": 209,
    "espionageprobe": 210,
    "sondadeespionagem": 210,
    "bomber": 211,
    "bombardeiro": 211,
    "destroyer": 213,
    "destruidor": 213,
    "deathstar": 214,
    "estreladamorte": 214,
    "battlecruiser": 215,
    "interceptor": 215,
    "reaper": 218,
    "ceifeira": 218,
    "pathfinder": 219,
    "exploradora": 219,
}

_COORDS_RE = re.compile(r"\[(\d+):(\d+):(\d+)\]")
_EVENT_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*eventFleet[^"]*"[^>]*>(.*?)</tr>',
    re.I | re.S,
)
_ACS_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*allianceAttack[^"]*"[^>]*>(.*?)</tr>',
    re.I | re.S,
)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_SHIP_ROW_RE = re.compile(
    r"<td>([^<]+)</td>\s*<td[^>]*>\s*([^<]+)\s*</td>",
    re.I,
)
_NORM_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class HostileAttack:
    id: int
    mission: int
    attacker_id: int
    attacker_name: str
    dest: Coords
    arrive_in: float
    origin: Coords | None = None
    ships: dict[int, int] | None = None
    missiles: int = 0


def _norm_ship_name(name: str) -> str:
    s = unicodedata.normalize("NFD", (name or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return _NORM_RE.sub("", s.rstrip(":").strip())


def ship_name_to_id(name: str) -> int | None:
    return _SHIP_NAME_ID.get(_norm_ship_name(name))


def fleet_points(ships: dict[int, int] | None) -> int:
    if not ships:
        return 0
    return sum(int(n) * _FLEET_POINTS.get(sid, 0) for sid, n in ships.items() if n > 0)


def is_only_probes(ships: dict[int, int] | None) -> bool:
    """TBot AttackerFleet.IsOnlyProbes."""
    if not ships:
        return False
    probes = int(ships.get(210) or 0)
    if probes <= 0:
        return False
    for sid, n in ships.items():
        if sid == 210 or int(n) <= 0:
            continue
        return False
    return True


def parse_ships_tooltip(title: str) -> dict[int, int] | None:
    raw = unescape(title or "")
    if "fleetinfo" not in raw and "<td>" not in raw.lower():
        return None
    out: dict[int, int] = {}
    for name, nbr in _SHIP_ROW_RE.findall(raw):
        sid = ship_name_to_id(name)
        if sid is None:
            continue
        s = (nbr or "").strip().replace(".", "").replace(",", "")
        if s == "?":
            out[sid] = -1
            continue
        try:
            n = int(s)
        except ValueError:
            continue
        if n > 0:
            out[sid] = n
    return out or None


def _attrs(tag_open: str) -> dict[str, str]:
    return {k.lower(): v for k, v in _ATTR_RE.findall(tag_open)}


def _coords_pair(row_html: str) -> tuple[Coords | None, Coords | None]:
    origin = None
    dest = None
    om = re.search(r'class="[^"]*coordsOrigin[^"]*"[^>]*>(.*?)</td>', row_html, re.I | re.S)
    if om:
        cm = _COORDS_RE.search(om.group(1))
        if cm:
            g, s, p = map(int, cm.groups())
            moon = bool(
                re.search(
                    r'class="[^"]*originFleet[^"]*"[^>]*>.*?class="[^"]*moon',
                    row_html,
                    re.I | re.S,
                )
            )
            origin = Coords(g, s, p, "Moon" if moon else "Planet")
    dm = re.search(r'class="[^"]*destCoords[^"]*"[^>]*>(.*?)</td>', row_html, re.I | re.S)
    if dm:
        cm = _COORDS_RE.search(dm.group(1))
        if cm:
            g, s, p = map(int, cm.groups())
            moon = bool(
                re.search(
                    r'class="[^"]*destFleet[^"]*"[^>]*>.*?class="[^"]*moon',
                    row_html,
                    re.I | re.S,
                )
            )
            dest = Coords(g, s, p, "Moon" if moon else "Planet")
    return origin, dest


def attack_alert_lit(page: Page) -> bool:
    """#attack_alert.soon|today — UI diz Ataque! mesmo com eventList AJAX vazio."""
    try:
        return bool(
            page.evaluate(
                """() => {
                  const a = document.querySelector('#attack_alert');
                  if (!a) return false;
                  return /\\b(soon|today)\\b/.test(a.className || '');
                }"""
            )
        )
    except Exception:
        return False


def _coords_match(
    c: Coords | None, galaxy: int, system: int, position: int, *, moon: bool
) -> bool:
    if c is None:
        return False
    want = "Moon" if moon else "Planet"
    return (
        c.galaxy == galaxy
        and c.system == system
        and c.position == position
        and c.type == want
    )


def count_own_ships_in_flight_html(
    html: str,
    ship_id: int,
    galaxy: int,
    system: int,
    position: int,
    *,
    moon: bool = False,
) -> int:
    """Sum ship_id on own (non-hostile) fleets from/to this celestial.

    Outbound → match origin; return → match dest. One live leg per fleet
    (ponytail: if both legs ever coexist, would double-count — rare).
    """
    total = 0
    for m in _EVENT_ROW_RE.finditer(html or ""):
        row = m.group(0)
        if re.search(
            r'class="[^"]*countDown[^"]*hostile|span[^>]*class="[^"]*hostile',
            row,
            re.I,
        ):
            continue
        open_tag = row[: row.find(">") + 1]
        attrs = _attrs(open_tag)
        is_return = (attrs.get("data-return-flight") or "") in ("true", "1")
        origin, dest = _coords_pair(row)
        if is_return:
            if not _coords_match(dest, galaxy, system, position, moon=moon):
                continue
        elif not _coords_match(origin, galaxy, system, position, moon=moon):
            continue
        tip = re.search(
            r'class="[^"]*icon_movement[^"]*".*?<span[^>]*title="([^"]*)"',
            row,
            re.I | re.S,
        )
        if not tip:
            continue
        ships = parse_ships_tooltip(tip.group(1)) or {}
        n = int(ships.get(ship_id) or 0)
        if n > 0:
            total += n
    return total


def count_own_ships_in_flight(
    page: Page,
    ship_id: int,
    galaxy: int,
    system: int,
    position: int,
    *,
    moon: bool = False,
) -> int:
    from .event_list import first_event_list_html

    return count_own_ships_in_flight_html(
        first_event_list_html(page),
        ship_id,
        galaxy,
        system,
        position,
        moon=moon,
    )


def parse_hostile_attacks_html(html: str, *, now: float | None = None) -> list[HostileAttack]:
    """Parse eventList AJAX HTML → hostile Attack/ACS/Spy/Destroy/IPM."""
    now = time.time() if now is None else now
    out: list[HostileAttack] = []
    for rx, force_mission in ((_ACS_ROW_RE, MISSION_ACS), (_EVENT_ROW_RE, None)):
        for m in rx.finditer(html):
            row = m.group(0)
            classes = re.search(r'class="([^"]*)"', row, re.I)
            if classes and "partnerinfo" in classes.group(1).lower():
                continue
            if not re.search(
                r'class="[^"]*countDown[^"]*hostile|span[^>]*class="[^"]*hostile',
                row,
                re.I,
            ):
                continue
            open_tag = row[: row.find(">") + 1]
            attrs = _attrs(open_tag)
            try:
                mission = int(attrs.get("data-mission-type") or "0")
            except ValueError:
                continue
            if force_mission is not None:
                mission = force_mission
            if mission not in _HOSTILE_MISSIONS:
                continue
            arrival_raw = attrs.get("data-arrival-time") or ""
            if not arrival_raw.isdigit():
                continue
            arrive_in = max(0.0, int(arrival_raw) - now)
            id_m = re.search(r"eventRow-(?:union)?(\d+)", attrs.get("id") or "", re.I)
            eid = int(id_m.group(1)) if id_m else 0
            pid_m = re.search(r'data-playerid="(\d+)"', row, re.I)
            attacker_id = int(pid_m.group(1)) if pid_m else 0
            title_m = re.search(
                r'class="[^"]*sendMail[^"]*"[^>]*title="([^"]*)"',
                row,
                re.I,
            ) or re.search(
                r'title="([^"]*)"[^>]*class="[^"]*sendMail',
                row,
                re.I,
            ) or re.search(
                r'data-playerid="\d+"[^>]*title="([^"]*)"',
                row,
                re.I,
            )
            attacker_name = unescape(title_m.group(1)) if title_m else "?"
            origin, dest = _coords_pair(row)
            if dest is None:
                continue
            ships = None
            tip = re.search(
                r'class="[^"]*icon_movement[^"]*".*?<span[^>]*title="([^"]*)"',
                row,
                re.I | re.S,
            )
            if tip:
                ships = parse_ships_tooltip(tip.group(1))
            missiles = 0
            if mission == MISSION_MISSILE:
                mm = re.search(
                    r'class="[^"]*detailsFleet[^"]*".*?<span[^>]*>\s*([\d.]+)\s*</span>',
                    row,
                    re.I | re.S,
                )
                if mm:
                    try:
                        missiles = int(mm.group(1).replace(".", ""))
                    except ValueError:
                        missiles = 0
            out.append(
                HostileAttack(
                    id=eid,
                    mission=mission,
                    attacker_id=attacker_id,
                    attacker_name=attacker_name,
                    dest=dest,
                    arrive_in=arrive_in,
                    origin=origin,
                    ships=ships,
                    missiles=missiles,
                )
            )
    return out


def list_hostile_attacks(page: Page) -> list[HostileAttack]:
    """Hostis via eventList AJAX + fallbacks DOM/refresh.

    No BR/Dione o AJAX `component=eventList` às vezes devolve tbody vazio
    enquanto o overview/#attack_alert já mostram o ataque — daí o bot
    mentia `safe`. Ordem: AJAX → DOM atual → refresh in-page → overview GET.
    """
    from .event_list import event_list_sources

    for html in event_list_sources(page):
        atks = parse_hostile_attacks_html(html)
        if atks:
            return atks
    return []
