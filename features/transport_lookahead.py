"""TB-03: empilhar N builds na fila clássica se 2×flight ≥ buildTime (TBot)."""
from __future__ import annotations

from features.transport_bundle import KIND_CLASSIC, BundlePart, sum_costs
from game import (
    Celestial,
    Tech,
    current_resources,
    open_component,
    parse_ogame_int,
    parse_technologies,
    peek_tech_costs,
)

# OGame cost multipliers per level (same-tid scale when DOM still shows L).
_COST_MULT = {
    1: 1.5,
    2: 1.6,
    3: 1.5,
    4: 1.5,
    12: 1.8,
    14: 2.0,
    15: 2.0,
    21: 2.0,
    22: 2.0,
    23: 2.0,
    24: 2.0,
    30: 2.0,
    31: 2.0,
    33: 2.0,
    36: 2.0,
    41: 2.0,
    42: 2.0,
    43: 2.0,
    44: 2.0,
}
_BASE_CARGO_SPEED = {202: 5000, 203: 7500}
_COMBUSTION, _IMPULSE = 115, 117


def cargo_speed(
    sid: int, combustion: int, impulse: int, *, collector: bool = False
) -> int:
    """TBot CalcShipSpeed for SC/LC. ponytail: skip LF/ally class; collector opt-in."""
    comb = max(0, int(combustion))
    imp = max(0, int(impulse))
    if sid == 202:  # SmallCargo
        base, bonus = 5000, comb
        if imp >= 5:
            base, bonus = 10000, imp * 2
    elif sid == 203:  # LargeCargo
        base, bonus = 7500, comb
    else:
        return _BASE_CARGO_SPEED.get(sid, 7500)
    if collector:
        bonus += 10
    return int(base * (bonus + 10) / 10)


def classic_build_secs(
    cost: dict[str, int], robots: int, nanites: int, eco_speed: int
) -> int:
    """Seconds to build; metal+crystal / (2500·(1+R)·speed·2^N) — TBot CalcProductionTime."""
    struct = int(cost.get("metal") or 0) + int(cost.get("crystal") or 0)
    if struct <= 0:
        return 10**9
    denom = (
        2500.0
        * (1 + max(0, robots))
        * max(1, eco_speed)
        * (2 ** max(0, nanites))
    )
    return max(1, int(struct / denom))


def scale_building_cost(cost: dict[str, int], tid: int) -> dict[str, int]:
    f = _COST_MULT.get(tid, 2.0)
    return {k: int(int(cost.get(k) or 0) * f) for k in ("metal", "crystal", "deut")}


def stack_classic_lookahead(
    techs: dict,
    am_cfg: dict,
    *,
    moon: bool,
    energy: int,
    seed_tid: int,
    seed_cost: dict[str, int],
    seed_tag: str,
    flight_one_way: int,
    eco_speed: int,
    peek_cost,
    max_extra: int = 5,
) -> tuple[dict[str, int], str, set[int]]:
    """Empilhar N builds na fila clássica enquanto 2×flight ≥ cum buildTime.

    peek_cost(tid) → cost dict | None. Same tid re-entry scales last cost (DOM stuck on L).
    """
    from features.automine_pick import ROBOTS, NANITES, SAT_ID, label, pick_next

    if flight_one_way <= 0 or seed_tid == SAT_ID:
        return dict(seed_cost), seed_tag, {seed_tid}

    sim = {
        tid: Tech(t.id, t.level, t.status, getattr(t, "name", ""))
        for tid, t in techs.items()
    }
    robots = sim[ROBOTS].level if ROBOTS in sim else 0
    nanites = sim[NANITES].level if NANITES in sim else 0
    total = dict(seed_cost)
    tags = [seed_tag]
    tids = {seed_tid}
    last_cost = {seed_tid: dict(seed_cost)}
    build_time = classic_build_secs(seed_cost, robots, nanites, eco_speed)
    cur = seed_tid

    for _ in range(max_extra):
        if flight_one_way * 2 < build_time:
            break
        if cur in sim:
            t = sim[cur]
            sim[cur] = Tech(t.id, t.level + 1, t.status, t.name)
        robots = sim[ROBOTS].level if ROBOTS in sim else 0
        nanites = sim[NANITES].level if NANITES in sim else 0
        # ponytail: energy/fields not simulated; pick may drift vs TBot on plant swaps
        nxt = pick_next(sim, am_cfg, moon, energy, afford=False)
        if nxt is None or nxt == SAT_ID:
            break
        if nxt in last_cost:
            nc = scale_building_cost(last_cost[nxt], nxt)
        else:
            nc = peek_cost(nxt)
            if not nc or sum(nc.values()) <= 0:
                break
            nc = {k: int(nc.get(k) or 0) for k in ("metal", "crystal", "deut")}
        last_cost[nxt] = nc
        total = sum_costs(total, nc)
        lvl = (sim[nxt].level + 1) if nxt in sim else "?"
        tags.append(f"{label(nxt)}→{lvl}")
        tids.add(nxt)
        build_time += classic_build_secs(nc, robots, nanites, eco_speed)
        cur = nxt

    return total, "+".join(tags), tids


def _drive_levels(page, cache=None) -> tuple[int, int]:
    """Combustion / Impulse from research (empire-wide)."""
    if cache is not None:
        techs = cache.techs("research")
    else:
        open_component(page, "research")
        techs = parse_technologies(page)
    comb = techs[_COMBUSTION].level if _COMBUSTION in techs else 0
    imp = techs[_IMPULSE].level if _IMPULSE in techs else 0
    return int(comb), int(imp)


def _flight_one_way(page, brain: dict, dest: Celestial, *, cache=None) -> int:
    from features.fleetsave import flight_secs
    from features.transports import resolve_origin
    from game.fleet import NAME_TO_ID, fleet_speed_peaceful
    from game.galaxy import ogame_distance

    tcfg = brain.get("Transports") or {}
    origin = resolve_origin(page, tcfg.get("Origin") or {})
    if origin is None or origin.id == dest.id:
        return 0
    dist = max(5, ogame_distance(origin.coords, dest.coords))
    cargo = str(tcfg.get("CargoType") or "LargeCargo")
    sid = NAME_TO_ID.get(cargo) or 203
    comb, imp = _drive_levels(page, cache)
    ship_spd = cargo_speed(sid, comb, imp)
    return flight_secs(dist, ship_spd, 10, fleet_speed_peaceful(page))


def _classic_techs(page, moon: bool, cache=None) -> dict:
    if cache is not None:
        if moon:
            return dict(cache.techs("facilities"))
        techs = dict(cache.techs("supplies"))
        techs.update(cache.techs("facilities"))
        return techs
    open_component(page, "supplies" if not moon else "facilities")
    techs = parse_technologies(page)
    if not moon:
        open_component(page, "facilities")
        techs.update(parse_technologies(page))
    return techs


def apply_classic_lookahead(
    page,
    brain: dict,
    celestial: Celestial,
    parts: list[BundlePart],
    classic_tid: int | None,
    *,
    cache=None,
    reasons: list | None = None,
) -> tuple[list[BundlePart], set[int]]:
    """Expand the classic BundlePart with same-queue stack. Skip moon / sats / no tid."""
    from features.automine_pick import FACILITY_IDS, SAT_ID
    from features.transport_bundle import note_reason
    from game.fleet import universe_speed

    tids: set[int] = {classic_tid} if classic_tid else set()
    if (
        classic_tid is None
        or classic_tid == SAT_ID
        or celestial.coords.type == "Moon"
    ):
        return parts, tids

    idx = next((i for i, p in enumerate(parts) if p[0] == KIND_CLASSIC), None)
    if idx is None:
        return parts, tids

    if cache is None:
        from features.transport_bundle import CelTechCache

        cache = CelTechCache(page)

    flight = _flight_one_way(page, brain, celestial, cache=cache)
    if flight <= 0:
        return parts, tids

    am = brain.get("AutoMine") or {}
    techs = _classic_techs(page, False, cache)
    energy = parse_ogame_int(current_resources(page).get("energy", "0"))
    _, cost, tag = parts[idx]

    def peek(tid: int):
        need = "facilities" if tid in FACILITY_IDS else "supplies"
        cache.techs(need)
        return peek_tech_costs(page, tid)

    total, new_tag, tids = stack_classic_lookahead(
        techs,
        am,
        moon=False,
        energy=energy,
        seed_tid=classic_tid,
        seed_cost=cost,
        seed_tag=tag,
        flight_one_way=flight,
        eco_speed=universe_speed(page),
        peek_cost=peek,
    )
    if new_tag != tag:
        note_reason(reasons, f"stack classic flight={flight}s → {new_tag}")
    parts = list(parts)
    parts[idx] = (KIND_CLASSIC, total, new_tag)
    return parts, tids


if __name__ == "__main__":
    assert cargo_speed(203, 0, 0) == 7500
    assert cargo_speed(203, 6, 0) == 12000
    assert cargo_speed(202, 6, 0) == 8000
    assert cargo_speed(202, 6, 5) == 20000
    assert cargo_speed(203, 0, 0, collector=True) == 15000
    assert classic_build_secs(
        {"metal": 2500, "crystal": 0, "deut": 0}, 0, 0, 1
    ) == 1
    assert classic_build_secs(
        {"metal": 5000, "crystal": 5000, "deut": 0}, 0, 0, 1
    ) == 4
    assert scale_building_cost(
        {"metal": 100, "crystal": 20, "deut": 0}, 1
    ) == {"metal": 150, "crystal": 30, "deut": 0}

    from features.automine_pick import METAL, CRYSTAL, DEUT, SOLAR

    techs = {
        METAL: Tech(METAL, 5, "on"),
        CRYSTAL: Tech(CRYSTAL, 10, "on"),
        DEUT: Tech(DEUT, 10, "on"),
        SOLAR: Tech(SOLAR, 20, "on"),
    }
    cfg = {
        "MaxMetalMine": 40,
        "MaxCrystalMine": 35,
        "MaxDeuteriumSynthetizer": 30,
        "MaxSolarPlant": 20,
        "MaxFusionReactor": 0,
        "OptimizeForStart": True,
    }
    seed = {"metal": 100, "crystal": 0, "deut": 0}

    def no_peek(_tid):
        return None

    total, tag, tids = stack_classic_lookahead(
        techs,
        cfg,
        moon=False,
        energy=100,
        seed_tid=METAL,
        seed_cost=seed,
        seed_tag="Metal→6",
        flight_one_way=10**9,
        eco_speed=1,
        peek_cost=no_peek,
        max_extra=2,
    )
    assert tids == {METAL}
    assert total["metal"] == 100 + 150 + 225
    assert tag.count("+") == 2
    fat = {"metal": 10_000, "crystal": 0, "deut": 0}
    total2, tag2, _ = stack_classic_lookahead(
        techs,
        cfg,
        moon=False,
        energy=100,
        seed_tid=METAL,
        seed_cost=fat,
        seed_tag="Metal→6",
        flight_one_way=1,
        eco_speed=1,
        peek_cost=no_peek,
        max_extra=2,
    )
    assert total2 == fat and tag2 == "Metal→6"
    print("transport_lookahead ok")
