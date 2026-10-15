"""E04-T02 Brain Transports: send missing resources Origin → destination."""
from __future__ import annotations

import math

from game import (
    Celestial,
    current_resources,
    fleet_slots,
    open_component,
    parse_celestials,
    parse_ogame_int,
    resource_storage,
    switch_celestial,
)
from game.fleet import (
    DEST_MOON,
    DEST_PLANET,
    MISSION_TRANSPORT,
    NAME_TO_ID,
    has_incoming_transport,
    parse_ships,
    send_fleet,
)
from runtime import slots_available

# reuse payload math from repatriate (same cargo fill rules)
from features.autorepatriate import clamp_payload, ships_for_payload


def missing_resources(cost: dict[str, int], have: dict[str, int]) -> dict[str, int]:
    return {
        "metal": max(0, int(cost.get("metal", 0)) - int(have.get("metal", 0))),
        "crystal": max(0, int(cost.get("crystal", 0)) - int(have.get("crystal", 0))),
        "deut": max(0, int(cost.get("deut", 0)) - int(have.get("deut", 0))),
    }


def round_resources(m: int, c: int, d: int, round_to: int = 1000) -> tuple[int, int, int]:
    """TBot Resources.Round — ceil each resource to round_to."""
    r = max(1, int(round_to))

    def _up(n: int) -> int:
        n = max(0, int(n))
        if n == 0:
            return 0
        return int(math.ceil(n / float(r)) * r)

    return _up(m), _up(c), _up(d)


def overflow_payload(
    need: dict[str, int],
    dest_have: dict[str, int],
    dest_storage: dict[str, int],
    origin_have: dict[str, int],
    origin_storage: dict[str, int],
    factor: float,
) -> dict[str, int]:
    """If Origin stock > storage×factor, send max(need, dest room to fill storage)."""
    out: dict[str, int] = {}
    for k in ("metal", "crystal", "deut"):
        n = max(0, int(need.get(k, 0)))
        ostore = int(origin_storage.get(k, 0))
        ohave = int(origin_have.get(k, 0))
        if factor > 0 and ostore > 0 and ohave > ostore * factor:
            room = max(0, int(dest_storage.get(k, 0)) - int(dest_have.get(k, 0)))
            out[k] = max(n, room)
        else:
            out[k] = n
    return out


def _match_origin(c: Celestial, origin: dict) -> bool:
    return (
        c.coords.galaxy == int(origin.get("Galaxy", -1))
        and c.coords.system == int(origin.get("System", -1))
        and c.coords.position == int(origin.get("Position", -1))
        and c.coords.type == (origin.get("Type") or "Planet")
    )


def resolve_origin(page, origin_cfg: dict) -> Celestial | None:
    if not origin_cfg:
        return None
    for c in parse_celestials(page):
        if _match_origin(c, origin_cfg):
            return c
    return None


def transports_enabled(brain: dict, feature_cfg: dict) -> bool:
    t = brain.get("Transports") or {}
    ft = feature_cfg.get("Transports") or {}
    return bool(brain.get("Active") and t.get("Active") and ft.get("Active"))


def send_miner_transport(
    page,
    brain: dict,
    dest: Celestial,
    cost: dict[str, int],
    *,
    leave_slots: int = 1,
) -> str:
    """Origin → dest with missing resources for `cost`. Short status string."""
    tcfg = brain.get("Transports") or {}
    if not (brain.get("Active") and tcfg.get("Active")):
        return "off"

    origin = resolve_origin(page, tcfg.get("Origin") or {})
    if origin is None:
        return "sem Origin"
    if origin.id == dest.id:
        return "mesmo celestial"

    # need dest stock from current page (caller should be on dest)
    res = current_resources(page)
    have = {
        "metal": parse_ogame_int(res.get("metal", "0")),
        "crystal": parse_ogame_int(res.get("crystal", "0")),
        "deut": parse_ogame_int(res.get("deut", "0")),
    }
    miss = missing_resources(cost, have)
    m, c, d = miss["metal"], miss["crystal"], miss["deut"]
    if m + c + d <= 0:
        return "noop"

    if has_incoming_transport(
        page,
        dest.coords.galaxy,
        dest.coords.system,
        dest.coords.position,
        moon=dest.coords.type == "Moon",
    ):
        return "incoming"

    dest_stor = resource_storage(page)

    switch_celestial(page, origin)
    open_component(page, "fleetdispatch")
    if not slots_available(fleet_slots(page), leave_slots):
        return "sem slot"

    ores = current_resources(page)
    om = parse_ogame_int(ores.get("metal", "0"))
    oc = parse_ogame_int(ores.get("crystal", "0"))
    od_raw = parse_ogame_int(ores.get("deut", "0"))
    leave = int(tcfg.get("DeutToLeave") or 0)
    od = max(0, od_raw - leave) if leave > 0 else od_raw

    factor = float(tcfg.get("OverflowFactor", 2) or 0)
    filled = overflow_payload(
        miss,
        have,
        dest_stor,
        {"metal": om, "crystal": oc, "deut": od_raw},
        resource_storage(page),
        factor,
    )
    used_fill = any(filled[k] > miss[k] for k in ("metal", "crystal", "deut"))
    m, c, d = min(filled["metal"], om), min(filled["crystal"], oc), min(filled["deut"], od)

    if tcfg.get("RoundResources", True):
        m, c, d = round_resources(m, c, d)
        m, c, d = min(m, om), min(c, oc), min(d, od)

    if m + c + d <= 0 or om < m or oc < c or od < d:
        return "origem sem recurso"

    cargo_name = str(tcfg.get("CargoType") or "LargeCargo")
    sid = NAME_TO_ID.get(cargo_name) or NAME_TO_ID["LargeCargo"]
    ships = parse_ships(page)
    have_n = ships.get(sid, {}).get("number", 0)
    cargo_per = ships.get(sid, {}).get("cargo", 0) or (25000 if sid == 203 else 5000)
    total = m + c + d
    n = ships_for_payload(total, cargo_per, have_n)
    if n <= 0:
        return "sem cargos"
    m, c, d = clamp_payload(m, c, d, n * cargo_per)
    if m + c + d <= 0:
        return "payload vazio"

    dest_type = DEST_MOON if dest.coords.type == "Moon" else DEST_PLANET
    status = send_fleet(
        page,
        {sid: n},
        dest.coords.galaxy,
        dest.coords.system,
        dest.coords.position,
        mission=MISSION_TRANSPORT,
        dest_type=dest_type,
        metal=m,
        crystal=c,
        deut=d,
    )
    if status == "ok":
        tag = "+fill" if used_fill else ""
        return f"ok {n}x{cargo_name} M{m}+C{c}+D{d}{tag}"
    return status


if __name__ == "__main__":
    assert missing_resources(
        {"metal": 1000, "crystal": 500, "deut": 100},
        {"metal": 200, "crystal": 500, "deut": 0},
    ) == {"metal": 800, "crystal": 0, "deut": 100}
    assert round_resources(1, 0, 1500) == (1000, 0, 2000)
    assert round_resources(0, 0, 0) == (0, 0, 0)
    # origin overflowing metal → fill dest metal room
    assert overflow_payload(
        {"metal": 100, "crystal": 50, "deut": 0},
        {"metal": 0, "crystal": 0, "deut": 0},
        {"metal": 10_000, "crystal": 5_000, "deut": 2_000},
        {"metal": 1_000_000, "crystal": 100, "deut": 0},
        {"metal": 10_000, "crystal": 10_000, "deut": 10_000},
        2.0,
    ) == {"metal": 10_000, "crystal": 50, "deut": 0}
    # factor off → exact need
    assert overflow_payload(
        {"metal": 100, "crystal": 0, "deut": 0},
        {"metal": 0, "crystal": 0, "deut": 0},
        {"metal": 10_000, "crystal": 0, "deut": 0},
        {"metal": 1_000_000, "crystal": 0, "deut": 0},
        {"metal": 10_000, "crystal": 0, "deut": 0},
        0,
    ) == {"metal": 100, "crystal": 0, "deut": 0}
    print("transports ok")
