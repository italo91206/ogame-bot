"""Shared fleetsave (E01-T03 + E02-T04): Deploy/Harvest/Spy/Colonize + recall."""
from __future__ import annotations

import json
import math
import random
import re
import time
from typing import Any

from playwright.sync_api import Page

from game import (
    Celestial,
    Coords,
    current_resources,
    open_component,
    parse_ogame_int,
    parse_slots,
    switch_celestial,
)
from game.fleet import (
    DEST_DEBRIS,
    DEST_MOON,
    DEST_PLANET,
    MISSION_COLONIZE,
    MISSION_DEPLOY,
    MISSION_HARVEST,
    MISSION_SPY,
    fleet_speed_peaceful,
    latest_outbound_fleet_id,
    parse_ships,
    recall_fleet,
    send_fleet,
)
from game.galaxy import (
    fetch_debris_near,
    fetch_empty_near,
    ogame_distance,
)
from game.tech import build_ships

_IMMOVABLE = frozenset({212, 217})
_LC, _SC, _PROBE, _CS, _RECY = 203, 202, 210, 208, 209
_SHIPS_DATA_RE = re.compile(r"var shipsData\s*=\s*")
_MISSION_NAME = {
    "deploy": MISSION_DEPLOY,
    "harvest": MISSION_HARVEST,
    "spy": MISSION_SPY,
    "colonize": MISSION_COLONIZE,
}


def movable_ships(ships: dict[int, dict[str, int]]) -> dict[int, int]:
    out: dict[int, int] = {}
    for sid, info in ships.items():
        if sid in _IMMOVABLE:
            continue
        n = int(info.get("number") or 0)
        if n > 0:
            out[sid] = n
    return out


def cargo_capacity(ships: dict[int, dict[str, int]], fleet: dict[int, int]) -> int:
    total = 0
    for sid, n in fleet.items():
        per = int(ships.get(sid, {}).get("cargo") or 0)
        if per <= 0:
            per = 25000 if sid == _LC else 5000 if sid == _SC else 0
        total += per * n
    return total


def parse_ships_data(html: str) -> dict[int, dict[str, Any]]:
    m = _SHIPS_DATA_RE.search(html)
    if not m:
        return {}
    i = html.find("{", m.end() - 1)
    if i < 0:
        return {}
    try:
        data, _ = json.JSONDecoder().raw_decode(html[i:])
    except json.JSONDecodeError:
        return {}
    return {
        int(k): v
        for k, v in data.items()
        if str(k).isdigit() and isinstance(v, dict)
    }


def flight_secs(
    dist: int, ship_speed: int, speed_tenths: int, uni_fleet_speed: int
) -> int:
    s = max(0.5, float(speed_tenths))
    v = max(1.0, float(ship_speed))
    a = max(1.0, float(uni_fleet_speed))
    d = max(1.0, float(dist))
    return int(round(((35000.0 / s) * math.sqrt(d * 10.0 / v) + 10.0) / a))


def slowest_speed(fleet: dict[int, int], ships_data: dict[int, dict]) -> int:
    best = 10**12
    for sid, n in fleet.items():
        if n <= 0:
            continue
        spd = int(ships_data.get(sid, {}).get("speed") or 0)
        if spd > 0:
            best = min(best, spd)
    return 1 if best >= 10**12 else best


def pick_speed(
    dist: int, ship_speed: int, uni_speed: int, min_one_way: float
) -> int:
    for spd in range(10, 0, -1):
        if flight_secs(dist, ship_speed, spd, uni_speed) >= min_one_way:
            return spd
    return 1


def clamp_payload(
    metal: int, crystal: int, deut: int, capacity: int, *, deut_leave: int
) -> tuple[int, int, int]:
    d = max(0, deut - max(0, deut_leave))
    cap = max(0, capacity)
    m = min(max(0, metal), cap)
    rem = cap - m
    c = min(max(0, crystal), rem)
    rem -= c
    return m, c, min(d, rem)


def ensure_cargos(
    page: Page, *, need: int, have_cargo: int, cargo_per: int = 25000
) -> str | None:
    if have_cargo >= need or need <= 0:
        return None
    missing = need - have_cargo
    n = max(1, int(math.ceil(missing / float(max(1, cargo_per)))))
    n = min(n, 200)  # teto sanity
    return build_ships(page, _LC, n)


def deploy_destinations(origin: Celestial, celestials: list[Celestial]) -> list[Coords]:
    others = [c for c in celestials if c.id != origin.id]
    moons = [c for c in others if c.coords.type == "Moon"]
    pool = moons or others
    return [
        c.coords
        for c in sorted(
            pool,
            key=lambda c: ogame_distance(origin.coords, c.coords),
            reverse=True,
        )
    ]


def spy_destinations(origin: Coords) -> list[Coords]:
    from game.galaxy import clamp_system

    return [
        Coords(origin.galaxy, clamp_system(origin.system + ds), 16, "Planet")
        for ds in range(-5, 6)
    ]


def mission_chain(default: str) -> list[int]:
    """TBot: default → Deploy ↔ Harvest → Colonize → Spy."""
    primary = _MISSION_NAME.get((default or "Deploy").strip().lower(), MISSION_DEPLOY)
    rest = [MISSION_DEPLOY, MISSION_HARVEST, MISSION_COLONIZE, MISSION_SPY]
    out = [primary]
    for m in rest:
        if m not in out:
            out.append(m)
    return out


def _dest_type(coords: Coords) -> int:
    if coords.type == "Moon":
        return DEST_MOON
    if coords.type == "Debris":
        return DEST_DEBRIS
    return DEST_PLANET


def _candidates(
    page: Page,
    origin: Celestial,
    celestials: list[Celestial],
    mission: int,
    fleet: dict[int, int],
) -> list[Coords]:
    if mission == MISSION_DEPLOY:
        return deploy_destinations(origin, celestials)
    if mission == MISSION_HARVEST:
        if fleet.get(_RECY, 0) <= 0:
            return []
        dfs = fetch_debris_near(page, origin.coords.galaxy, origin.coords.system)
        return [d.coords for d in sorted(dfs, key=lambda x: x.total, reverse=True)]
    if mission == MISSION_COLONIZE:
        if fleet.get(_CS, 0) <= 0:
            return []
        return fetch_empty_near(page, origin.coords.galaxy, origin.coords.system)
    if mission == MISSION_SPY:
        if fleet.get(_PROBE, 0) <= 0:
            return []
        return spy_destinations(origin.coords)
    return []


def process_recalls(
    page: Page, recalls: list[dict[str, Any]], tui: Any = None
) -> int:
    """Executa recalls vencidos in-place na lista."""
    if not recalls:
        return 0
    now = time.time()
    keep: list[dict[str, Any]] = []
    done = 0
    for r in recalls:
        if float(r.get("at") or 0) > now:
            keep.append(r)
            continue
        fid = int(r.get("id") or 0)
        if not fid:
            continue
        try:
            st = recall_fleet(page, fid)
        except Exception as e:
            st = f"fail: {e}"
        if tui:
            tui.log(f"Fleetsave: recall {fid} {st}", "ok" if st == "ok" else "warn")
        if st == "ok":
            done += 1
        else:
            keep.append(r)  # retry next tick
    recalls.clear()
    recalls.extend(keep)
    return done


def fleetsave_celestial(
    page: Page,
    origin: Celestial,
    celestials: list[Celestial],
    *,
    min_duration: float,
    deut_to_leave: int = 0,
    build_cargos: bool = False,
    default_mission: str = "Deploy",
    recall: bool = False,
    recalls: list[dict[str, Any]] | None = None,
) -> str:
    """Ghost/fleetsave. ok:… / fail:… / skip:…"""
    switch_celestial(page, origin)
    if parse_slots(page).free < 1:
        return "fail: sem slot"

    open_component(page, "fleetdispatch")
    html = page.content()
    ships = parse_ships(page)
    fleet = movable_ships(ships)
    if not fleet:
        if build_cargos:
            why = ensure_cargos(page, need=25_000, have_cargo=0)
            return f"skip: sem frota · build {why or 'LC ok'}"
        return "skip: sem frota"

    res = current_resources(page)
    metal = parse_ogame_int(res.get("metal", "0"))
    crystal = parse_ogame_int(res.get("crystal", "0"))
    deut = parse_ogame_int(res.get("deut", "0"))
    if deut <= 0:
        return "skip: sem deut"

    cap = cargo_capacity(ships, fleet)
    need = metal + crystal + max(0, deut - deut_to_leave)
    if build_cargos and cap < need and need > 0:
        per = int(ships.get(_LC, {}).get("cargo") or 25000)
        why = ensure_cargos(page, need=need, have_cargo=cap, cargo_per=per)
        if why is None:
            open_component(page, "fleetdispatch")
            ships = parse_ships(page)
            fleet = movable_ships(ships)
            if not fleet:
                return "skip: sem frota pós-build"
            cap = cargo_capacity(ships, fleet)
            html = page.content()
        else:
            # ainda tenta salvar o que cabe
            pass

    ships_data = parse_ships_data(html)
    ship_spd = slowest_speed(fleet, ships_data)
    uni_spd = fleet_speed_peaceful(page)
    m, cr, d = clamp_payload(metal, crystal, deut, cap, deut_leave=deut_to_leave)

    last = "fail: destino"
    for mission in mission_chain(default_mission):
        # round-trip: one-way >= min/2; Deploy: full min
        need_ow = min_duration if mission == MISSION_DEPLOY else min_duration / 2.0
        try:
            dests = _candidates(page, origin, celestials, mission, fleet)
        except Exception as e:
            last = f"fail: scan {e}"
            continue
        for dest in dests:
            dist = max(5, ogame_distance(origin.coords, dest))
            spd = pick_speed(dist, ship_spd, uni_spd, need_ow)
            eta = flight_secs(dist, ship_spd, spd, uni_spd)
            open_component(page, "fleetdispatch")
            status = send_fleet(
                page,
                fleet,
                dest.galaxy,
                dest.system,
                dest.position,
                mission=mission,
                speed=spd,
                dest_type=_dest_type(dest),
                metal=m,
                crystal=cr,
                deut=d,
            )
            if status != "ok":
                last = status
                continue
            label = f"ok: {origin.label}→{dest} m{mission} spd{spd*10}% ~{eta:.0f}s"
            if recall and recalls is not None:
                # eventList pode estar na overview; tenta movement/fleetdispatch
                open_component(page, "fleetdispatch")
                fid = latest_outbound_fleet_id(
                    page,
                    galaxy=dest.galaxy,
                    system=dest.system,
                    position=dest.position,
                    mission=mission,
                )
                if fid:
                    delay = max(30.0, min_duration / 2.0) + random.uniform(60.0, 120.0)
                    recalls.append({"id": fid, "at": time.time() + delay})
                    label += f" · recall id={fid} @{delay:.0f}s"
                else:
                    label += " · recall fail: sem fleetId"
            elif not recall:
                label += " · recall off"
            return label
    return last


def attack_min_duration(arrive_in: float) -> float:
    return arrive_in + (arrive_in / 100.0 * 30.0) + random.uniform(5.0, 45.0)


if __name__ == "__main__":
    assert movable_ships({203: {"number": 2}, 212: {"number": 9}}) == {203: 2}
    assert mission_chain("Harvest")[0] == MISSION_HARVEST
    assert MISSION_DEPLOY in mission_chain("Harvest")
    assert pick_speed(20_000, 100, 1, 10**9) == 1
    assert pick_speed(20_000, 100, 1, 1) == 10
    o = Celestial("1", "A", Coords(1, 1, 1, "Planet"))
    m = Celestial("2", "B", Coords(1, 1, 1, "Moon"))
    assert deploy_destinations(o, [o, m])[0].type == "Moon"
    print("fleetsave ok")
