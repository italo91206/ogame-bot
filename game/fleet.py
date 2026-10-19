"""Fleet dispatch: ships, expo send (AJAX like ogamed)."""
from __future__ import annotations

import json
import math
import re
import time

from playwright.sync_api import Page

from .tech import open_component

# civil / combat IDs used by expeditions
SHIP_NAMES = {
    202: "SmallCargo",
    203: "LargeCargo",
    204: "LightFighter",
    205: "HeavyFighter",
    206: "Cruiser",
    207: "Battleship",
    208: "ColonyShip",
    209: "Recycler",
    210: "EspionageProbe",
    211: "Bomber",
    213: "Destroyer",
    214: "Deathstar",
    215: "Battlecruiser",
    218: "Reaper",
    219: "Pathfinder",
}
NAME_TO_ID = {v: k for k, v in SHIP_NAMES.items()}
# TBot CalcMilitaryShipForExpedition priority
_MILITARY = (218, 213, 211, 215, 207, 219, 206, 205, 204)


def _meta(page: Page, name: str, default: str = "") -> str:
    loc = page.locator(f'meta[name="{name}"]')
    if loc.count():
        return loc.first.get_attribute("content") or default
    return default


def universe_speed(page: Page) -> int:
    try:
        return max(1, int(_meta(page, "ogame-universe-speed", "1")))
    except ValueError:
        return 1


def fleet_speed_peaceful(page: Page) -> int:
    for name in (
        "ogame-universe-speed-fleet-peaceful",
        "ogame-universe-speed-fleet",
        "ogame-universe-speed",
    ):
        raw = _meta(page, name, "")
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
    return 1


def is_discoverer(page: Page) -> bool:
    title = ""
    loc = page.locator("#characterclass a, #characterclass")
    if loc.count():
        title = loc.first.get_attribute("title") or ""
    return "Discoverer" in title or "Explorador" in title or "Entdeck" in title


def parse_ships(page: Page) -> dict[int, dict[str, int]]:
    """id → {number, cargo}. Prefer shipsOnPlanet JS; fallback li.technology."""
    html = page.content()
    m = re.search(r"var shipsOnPlanet = (\[[^\]]*\]);", html)
    if m:
        try:
            rows = json.loads(m.group(1))
            out: dict[int, dict[str, int]] = {}
            for r in rows:
                sid = int(r["id"])
                out[sid] = {
                    "number": int(r.get("number") or 0),
                    "cargo": int(r.get("cargoCapacity") or r.get("baseCargoCapacity") or 0),
                }
            return out
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    out = {}
    items = page.locator("li.technology[data-technology]")
    for i in range(items.count()):
        li = items.nth(i)
        tid = li.get_attribute("data-technology") or ""
        if not tid.isdigit() or int(tid) not in SHIP_NAMES:
            continue
        amt = li.locator(".amount[data-value], .level[data-value]")
        n = int(amt.first.get_attribute("data-value") or "0") if amt.count() else 0
        out[int(tid)] = {"number": n, "cargo": 0}
    return out


from .discovery import send_discovery  # noqa: E402 — re-export public API
from .fleet_dispatch import (  # noqa: E402 — re-export public API
    DEST_DEBRIS,
    DEST_MOON,
    DEST_PLANET,
    MISSION_ATTACK,
    MISSION_COLONIZE,
    MISSION_DEPLOY,
    MISSION_DISCOVERY,
    MISSION_EXPEDITION,
    MISSION_HARVEST,
    MISSION_SPY,
    MISSION_TRANSPORT,
    send_fleet,
)
from .fleet_ui import send_fleet_ui  # noqa: E402


def send_expedition(
    page: Page,
    ships: dict[int, int],
    galaxy: int,
    system: int,
    *,
    holding: int = 1,
    deut: int = 0,
) -> str:
    """Send expo to [g:s:16]. V13: UI fleetDispatcher (AJAX checkTarget quebra com #100)."""
    return send_fleet_ui(
        page,
        ships,
        galaxy,
        system,
        16,
        mission=MISSION_EXPEDITION,
        speed=10,
        dest_type=DEST_PLANET,
        holding=holding,
        deut=deut,
    )

_COORDS_RE = re.compile(r"\[(\d+):(\d+):(\d+)\]")
_RECALL_HREF_RE = re.compile(
    r'component=movement[^"\']*return=(\d+)[^"\']*token=([a-f0-9]+)',
    re.I,
)
_EVENT_ID_RE = re.compile(r"eventRow-(\d+)", re.I)


def latest_outbound_fleet_id(
    page: Page,
    *,
    galaxy: int,
    system: int,
    position: int,
    mission: int,
) -> int | None:
    """Maior eventRow id outbound matching dest+mission (pós-send)."""
    base = page.url.split("?")[0]
    url = f"{base}?page=componentOnly&component=eventList&ajax=1"
    try:
        html = page.request.get(
            url, headers={"X-Requested-With": "XMLHttpRequest"}
        ).text() or ""
    except Exception:
        html = page.content()
    best: int | None = None
    for m in re.finditer(
        rf'<tr[^>]*id="eventRow-(\d+)"[^>]*data-mission-type="{int(mission)}"[^>]*>'
        r"(.*?)</tr>",
        html,
        re.I | re.S,
    ):
        fid = int(m.group(1))
        row = m.group(0)
        if re.search(r'data-return-flight="(?:true|1)"', row, re.I):
            continue
        # destCoords is usually the last coords link in row
        coords = _COORDS_RE.findall(row)
        if not coords:
            continue
        g, s, p = (int(x) for x in coords[-1])
        if g != galaxy or s != system or p != position:
            continue
        if best is None or fid > best:
            best = fid
    return best


def recall_fleet(page: Page, fleet_id: int) -> str:
    """Recall via movement?return=&token= (ogamed cancelFleet)."""
    open_component(page, "movement")
    html = page.content()
    token = None
    for m in _RECALL_HREF_RE.finditer(html):
        if int(m.group(1)) == int(fleet_id):
            token = m.group(2)
            break
    if not token:
        return "fail: sem token recall"
    base = page.url.split("?")[0]
    page.goto(
        f"{base}?page=ingame&component=movement&return={int(fleet_id)}&token={token}",
        wait_until="domcontentloaded",
    )
    page.wait_for_timeout(800)
    return "ok"


def _event_list_html(page: Page) -> str:
    base = page.url.split("?")[0]
    url = f"{base}?page=componentOnly&component=eventList&ajax=1"
    try:
        return page.request.get(
            url, headers={"X-Requested-With": "XMLHttpRequest"}
        ).text() or ""
    except Exception:
        return page.content()


def transport_arrive_in(
    page: Page, galaxy: int, system: int, position: int, *, moon: bool
) -> float | None:
    """Seconds until earliest inbound transport (mission 3 outbound) to dest."""
    now = time.time()
    best: float | None = None
    html = _event_list_html(page)
    for m in re.finditer(
        r'<tr[^>]*data-mission-type="3"[^>]*>.*?</tr>',
        html,
        re.I | re.S,
    ):
        row = m.group(0)
        if re.search(r'data-return-flight="(?:true|1)"', row, re.I):
            continue
        coords = _COORDS_RE.findall(row)
        if not coords:
            continue
        g, s, p = (int(x) for x in coords[-1])
        if g != galaxy or s != system or p != position:
            continue
        dest_fleet = ""
        dm = re.search(r'class="[^"]*destFleet[^"]*"[^>]*>([^<]*)', row, re.I)
        if dm:
            dest_fleet = dm.group(1)
        is_moon = "moon" in dest_fleet.lower() or "lua" in dest_fleet.lower()
        if is_moon != moon:
            continue
        am = re.search(r'data-arrival-time="(\d+)"', row, re.I)
        if not am:
            continue
        eta = int(am.group(1)) - now
        if eta < 0:
            continue
        if best is None or eta < best:
            best = eta
    if best is not None:
        return best
    # fallback: live DOM (same page may already have eventbox)
    rows = page.locator('tr.eventFleet[data-mission-type="3"]')
    for i in range(rows.count()):
        el = rows.nth(i)
        ret = el.get_attribute("data-return-flight") or ""
        if ret in ("true", "1"):
            continue
        dest = (
            el.locator("td.destCoords").inner_text()
            if el.locator("td.destCoords").count()
            else ""
        )
        cm = _COORDS_RE.search(dest)
        if not cm:
            continue
        if (
            int(cm.group(1)) != galaxy
            or int(cm.group(2)) != system
            or int(cm.group(3)) != position
        ):
            continue
        dest_fleet = (
            el.locator("td.destFleet").inner_text()
            if el.locator("td.destFleet").count()
            else ""
        )
        is_moon = "moon" in dest_fleet.lower() or "lua" in dest_fleet.lower()
        if is_moon != moon:
            continue
        arrival = el.get_attribute("data-arrival-time")
        if not arrival or not arrival.isdigit():
            continue
        eta = int(arrival) - now
        if eta < 0:
            continue
        if best is None or eta < best:
            best = eta
    return best


def has_incoming_transport(
    page: Page, galaxy: int, system: int, position: int, *, moon: bool
) -> bool:
    """True if outbound transport (mission 3) targets this celestial."""
    return transport_arrive_in(page, galaxy, system, position, moon=moon) is not None


def expo_back_in(page: Page, *, latest: bool = False) -> float | None:
    """Seconds until earliest (or latest) expedition return."""
    now = time.time()
    best: float | None = None
    rows = page.locator(
        'tr.eventFleet[data-mission-type="15"], '
        'div.fleetDetails[data-mission-type="15"]'
    )
    for i in range(rows.count()):
        el = rows.nth(i)
        arrival = el.get_attribute("data-arrival-time")
        if not arrival or not arrival.isdigit():
            continue
        eta = int(arrival) - now
        if eta < 0:
            continue
        ret = el.get_attribute("data-return-flight") or ""
        # prefer return legs; outbound still useful as lower bound
        weight = eta if ret in ("true", "1") else eta + 3600
        if best is None or (weight > best if latest else weight < best):
            best = weight
    return best


def earliest_expo_back_in(page: Page) -> float | None:
    return expo_back_in(page, latest=False)


def fleets_delay_until_sleep(page: Page, sleep_secs: float) -> float:
    """Max ETA (s) of non-Discovery fleets landing within sleep window; 0 = ok.

    Outbound legs delay until dest arrival; return legs appear next tick (TBot BackIn).
    """
    if sleep_secs <= 0:
        return 0.0
    now = time.time()
    delay = 0.0
    rows = page.locator("tr.eventFleet")
    for i in range(rows.count()):
        el = rows.nth(i)
        mission = el.get_attribute("data-mission-type") or ""
        if mission == str(MISSION_DISCOVERY):
            continue
        arrival = el.get_attribute("data-arrival-time")
        if not arrival or not arrival.isdigit():
            continue
        eta = int(arrival) - now
        if 0 <= eta <= sleep_secs:
            delay = max(delay, eta)
    return delay


def freight_cap(
    top_score: float,
    *,
    discoverer: bool,
    eco_speed: int,
    lf_resources_bonus: float = 0.0,
) -> int:
    """TBot CalcIdealExpeditionShips freightCap."""
    if top_score < 10_000:
        cap = 40_000
    elif top_score < 100_000:
        cap = 500_000
    elif top_score < 1_000_000:
        cap = 1_200_000
    elif top_score < 5_000_000:
        cap = 1_800_000
    elif top_score < 25_000_000:
        cap = 2_400_000
    elif top_score < 50_000_000:
        cap = 3_000_000
    elif top_score < 75_000_000:
        cap = 3_600_000
    elif top_score < 100_000_000:
        cap = 4_200_000
    else:
        cap = 5_000_000
    if discoverer:
        cap = cap * max(1, eco_speed) * 3
    else:
        cap *= 2
    if lf_resources_bonus > 0:
        cap += int(math.ceil(cap * lf_resources_bonus / 100.0))
    return cap


def pick_extras(available: dict[int, dict[str, int]], expos: int) -> dict[int, int]:
    """+1 probe, +1 military, +1 pathfinder when stock covers all expos."""
    extra: dict[int, int] = {}
    if expos <= 0:
        return extra
    if available.get(210, {}).get("number", 0) >= expos:
        extra[210] = 1
    for mid in _MILITARY:
        if available.get(mid, {}).get("number", 0) >= expos:
            extra[mid] = 1
            break
    if available.get(219, {}).get("number", 0) >= expos and 219 not in extra:
        extra[219] = 1
    return extra


if __name__ == "__main__":
    assert MISSION_EXPEDITION == 15
    assert freight_cap(6_103_492, discoverer=False, eco_speed=1) > 0
    print("fleet ok")

