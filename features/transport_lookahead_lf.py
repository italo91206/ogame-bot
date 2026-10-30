"""TB-C5: empilhar N builds/techs LF na mesma fila se 2×flight ≥ buildTime (TBot)."""
from __future__ import annotations

import re

from features.lf_prod_tables import (
    LF_BUILD_COST_F,
    LF_BUILD_TIME,
    LF_TECH_COST_F,
    LF_TECH_TIME,
)
from features.transport_bundle import KIND_LF_BUILD, KIND_LF_TECH, BundlePart, sum_costs
from game import (
    Celestial,
    Population,
    Tech,
    current_resources,
    lf_research_queue,
    parse_ogame_int,
    parse_population,
    peek_tech_costs,
)

_TID_RE = re.compile(r"LF(?:tech)?#(\d+)", re.I)


def tid_from_lf_tag(tag: str) -> int | None:
    m = _TID_RE.search(tag or "")
    return int(m.group(1)) if m else None


def lf_build_secs(
    tid: int, level: int, robots: int, nanites: int, eco_speed: int
) -> int:
    """Seconds for LF building L; TBot CalcLFTime(+robots/nanites)."""
    base, factor = LF_BUILD_TIME.get(tid, (2000, 1.3))
    if level <= 0 or base <= 0:
        return 10**9
    duration = round(level * base * (factor**level))
    duration = round(duration / ((max(0, robots) + 1) * (2 ** max(0, nanites))))
    duration = round(duration / max(1, eco_speed))
    return max(1, int(duration))


def lf_tech_secs(tid: int, level: int, eco_speed: int) -> int:
    """Seconds for LF tech L; TBot CalcLFTime (no robots)."""
    base, factor = LF_TECH_TIME.get(tid, (5000, 1.3))
    if level <= 0 or base <= 0:
        return 10**9
    duration = int(level * base * (factor**level))
    duration = int(duration / max(1, eco_speed))
    return max(1, duration)


def scale_lf_cost(cost: dict[str, int], tid: int, *, tech: bool = False) -> dict[str, int]:
    table = LF_TECH_COST_F if tech else LF_BUILD_COST_F
    f = table.get(tid, 1.3)
    return {k: int(int(cost.get(k) or 0) * f) for k in ("metal", "crystal", "deut")}


def stack_lf_build_lookahead(
    techs: dict,
    cfg: dict,
    *,
    seed_tid: int,
    seed_cost: dict[str, int],
    seed_tag: str,
    seed_level: int,
    flight_one_way: int,
    eco_speed: int,
    robots: int,
    nanites: int,
    peek_cost,
    pop: Population | None = None,
    energy: int = 0,
    prevent_tech: bool = False,
    mine_cost: dict[str, int] | None = None,
    max_extra: int = 5,
) -> tuple[dict[str, int], str]:
    """Empilhar N prédios LF enquanto 2×flight ≥ cum buildTime."""
    from features.lifeform_automine_pick import lf_beats_mine, pick_next

    if flight_one_way <= 0:
        return dict(seed_cost), seed_tag

    sim = {
        tid: Tech(t.id, t.level, t.status, getattr(t, "name", ""))
        for tid, t in techs.items()
    }
    total = dict(seed_cost)
    tags = [seed_tag]
    last_cost = {seed_tid: dict(seed_cost)}
    build_time = lf_build_secs(seed_tid, seed_level, robots, nanites, eco_speed)
    cur = seed_tid

    for _ in range(max_extra):
        if flight_one_way * 2 < build_time:
            break
        if cur in sim:
            t = sim[cur]
            sim[cur] = Tech(t.id, t.level + 1, t.status, t.name)
        # ponytail: pop living/food not re-sim'd; pick may drift vs TBot
        nxt = pick_next(
            sim,
            cfg,
            afford=False,
            prevent_tech=prevent_tech,
            pop=pop,
            energy=energy,
        )
        if nxt is None:
            break
        if nxt in last_cost:
            nc = scale_lf_cost(last_cost[nxt], nxt, tech=False)
        else:
            nc = peek_cost(nxt)
            if not nc or sum(nc.values()) <= 0:
                break
            nc = {k: int(nc.get(k) or 0) for k in ("metal", "crystal", "deut")}
        if mine_cost is not None and lf_beats_mine(nc, mine_cost):
            break
        last_cost[nxt] = nc
        total = sum_costs(total, nc)
        lvl = (sim[nxt].level + 1) if nxt in sim else "?"
        tags.append(f"LF#{nxt}→{lvl}")
        build_time += lf_build_secs(nxt, int(lvl) if lvl != "?" else 1, robots, nanites, eco_speed)
        cur = nxt

    return total, "+".join(tags)


def stack_lf_tech_lookahead(
    techs: dict,
    cfg: dict,
    *,
    seed_tid: int,
    seed_cost: dict[str, int],
    seed_tag: str,
    seed_level: int,
    flight_one_way: int,
    eco_speed: int,
    peek_cost,
    max_extra: int = 5,
) -> tuple[dict[str, int], str]:
    """Empilhar N techs LF enquanto 2×flight ≥ cum researchTime."""
    from features.lifeform_autoresearch_pick import pick_next

    if flight_one_way <= 0:
        return dict(seed_cost), seed_tag

    sim = {
        tid: Tech(t.id, t.level, t.status, getattr(t, "name", ""))
        for tid, t in techs.items()
    }
    total = dict(seed_cost)
    tags = [seed_tag]
    last_cost = {seed_tid: dict(seed_cost)}
    build_time = lf_tech_secs(seed_tid, seed_level, eco_speed)
    cur = seed_tid

    for _ in range(max_extra):
        if flight_one_way * 2 < build_time:
            break
        if cur in sim:
            t = sim[cur]
            sim[cur] = Tech(t.id, t.level + 1, t.status, t.name)
        nxt = pick_next(sim, cfg, afford=False)
        if nxt is None:
            break
        if nxt in last_cost:
            nc = scale_lf_cost(last_cost[nxt], nxt, tech=True)
        else:
            nc = peek_cost(nxt)
            if not nc or sum(nc.values()) <= 0:
                break
            nc = {k: int(nc.get(k) or 0) for k in ("metal", "crystal", "deut")}
        last_cost[nxt] = nc
        total = sum_costs(total, nc)
        lvl = (sim[nxt].level + 1) if nxt in sim else "?"
        tags.append(f"LFtech#{nxt}→{lvl}")
        build_time += lf_tech_secs(nxt, int(lvl) if lvl != "?" else 1, eco_speed)
        cur = nxt

    return total, "+".join(tags)


def _level_from_tag(tag: str, techs: dict, tid: int) -> int:
    m = re.search(r"→(\d+)", tag or "")
    if m:
        return int(m.group(1))
    return (techs[tid].level + 1) if tid in techs else 1


def apply_lf_build_lookahead(
    page,
    brain: dict,
    celestial: Celestial,
    parts: list[BundlePart],
    lf_tid: int | None,
    *,
    cache=None,
    reasons: list | None = None,
) -> list[BundlePart]:
    """Expand KIND_LF_BUILD part with same-queue stack. Skip moon / no part."""
    from features.automine_pick import NANITES, ROBOTS
    from features.transport_bundle import note_reason
    from features.transport_lookahead import _flight_one_way
    from game.fleet import universe_speed

    if celestial.coords.type == "Moon":
        return parts
    idx = next((i for i, p in enumerate(parts) if p[0] == KIND_LF_BUILD), None)
    if idx is None:
        return parts
    _, cost, tag = parts[idx]
    tid = lf_tid or tid_from_lf_tag(tag)
    if tid is None:
        return parts

    if cache is None:
        from features.transport_bundle import CelTechCache

        cache = CelTechCache(page)

    flight = _flight_one_way(page, brain, celestial, cache=cache)
    if flight <= 0:
        return parts

    cfg = brain.get("LifeformAutoMine") or {}
    fac = cache.techs("facilities")
    robots = fac[ROBOTS].level if ROBOTS in fac else 0
    nanites = fac[NANITES].level if NANITES in fac else 0
    techs = cache.techs("lfbuildings")
    pop = parse_population(page)
    energy = parse_ogame_int(current_resources(page).get("energy", "0"))
    prevent_tech = lf_research_queue(page)[0] != 0
    seed_level = _level_from_tag(tag, techs, tid)

    mine_cost = None
    if cfg.get("PreventIfMoreExpensiveThanNextMine"):
        supplies = cache.techs("supplies")
        from features.automine_pick import CRYSTAL, DEUT, METAL

        mines = [
            t
            for mid in (METAL, CRYSTAL, DEUT)
            if (t := supplies.get(mid)) and t.status in ("on", "disabled")
        ]
        if mines:
            mid = min(mines, key=lambda t: t.level).id
            mc = peek_tech_costs(page, mid)
            if mc:
                mine_cost = {k: int(mc.get(k) or 0) for k in ("metal", "crystal", "deut")}
        cache.techs("lfbuildings")

    def peek(nid: int):
        cache.techs("lfbuildings")
        return peek_tech_costs(page, nid)

    total, new_tag = stack_lf_build_lookahead(
        techs,
        cfg,
        seed_tid=tid,
        seed_cost=cost,
        seed_tag=tag,
        seed_level=seed_level,
        flight_one_way=flight,
        eco_speed=universe_speed(page),
        robots=robots,
        nanites=nanites,
        peek_cost=peek,
        pop=pop,
        energy=energy,
        prevent_tech=prevent_tech,
        mine_cost=mine_cost,
    )
    if new_tag != tag:
        note_reason(reasons, f"stack lf_build flight={flight}s → {new_tag}")
    parts = list(parts)
    parts[idx] = (KIND_LF_BUILD, total, new_tag)
    return parts


def apply_lf_tech_lookahead(
    page,
    brain: dict,
    celestial: Celestial,
    parts: list[BundlePart],
    lf_tid: int | None,
    *,
    cache=None,
    reasons: list | None = None,
) -> list[BundlePart]:
    """Expand KIND_LF_TECH part with same-queue stack. Skip moon / no part."""
    from features.transport_bundle import note_reason
    from features.transport_lookahead import _flight_one_way
    from game.fleet import universe_speed

    if celestial.coords.type == "Moon":
        return parts
    idx = next((i for i, p in enumerate(parts) if p[0] == KIND_LF_TECH), None)
    if idx is None:
        return parts
    _, cost, tag = parts[idx]
    tid = lf_tid or tid_from_lf_tag(tag)
    if tid is None:
        return parts

    if cache is None:
        from features.transport_bundle import CelTechCache

        cache = CelTechCache(page)

    flight = _flight_one_way(page, brain, celestial, cache=cache)
    if flight <= 0:
        return parts

    cfg = brain.get("LifeformAutoResearch") or {}
    techs = cache.techs("lfresearch")
    seed_level = _level_from_tag(tag, techs, tid)

    def peek(nid: int):
        cache.techs("lfresearch")
        return peek_tech_costs(page, nid)

    total, new_tag = stack_lf_tech_lookahead(
        techs,
        cfg,
        seed_tid=tid,
        seed_cost=cost,
        seed_tag=tag,
        seed_level=seed_level,
        flight_one_way=flight,
        eco_speed=universe_speed(page),
        peek_cost=peek,
    )
    if new_tag != tag:
        note_reason(reasons, f"stack lf_tech flight={flight}s → {new_tag}")
    parts = list(parts)
    parts[idx] = (KIND_LF_TECH, total, new_tag)
    return parts


if __name__ == "__main__":
    # ResidentialSector L1: 1*40*1.21^1 / 1 / 1 = 48
    assert lf_build_secs(11101, 1, 0, 0, 1) == 48
    # ResearchAI-ish: IntergalacticEnvoys L1 → 1*1000*1.2 = 1200
    assert lf_tech_secs(11201, 1, 1) == 1200
    assert scale_lf_cost(
        {"metal": 100, "crystal": 0, "deut": 0}, 11101
    ) == {"metal": 120, "crystal": 0, "deut": 0}
    assert tid_from_lf_tag("LF#11101→5") == 11101
    assert tid_from_lf_tag("LFtech#11202→3") == 11202

    # só 1 cand → same-tid scale (factor 1.2)
    techs = {11101: Tech(11101, 5, "on")}
    cfg = {
        "MaxBasePopulationBuilding": 60,
        "MaxBaseFoodBuilding": 62,
        "MaxBaseTechBuilding": 6,
        "MaxT2Building": 10,
        "MaxT3Building": 8,
        "MaxBuilding6": 5,
        "MaxBuilding7": 5,
        "MaxBuilding8": 5,
        "MaxBuilding9": 5,
        "MaxBuilding10": 5,
        "MaxBuilding11": 5,
        "MaxBuilding12": 5,
    }
    seed = {"metal": 100, "crystal": 0, "deut": 0}

    def no_peek(_tid):
        return None

    total, tag = stack_lf_build_lookahead(
        techs,
        cfg,
        seed_tid=11101,
        seed_cost=seed,
        seed_tag="LF#11101→6",
        seed_level=6,
        flight_one_way=10**9,
        eco_speed=1,
        robots=0,
        nanites=0,
        peek_cost=no_peek,
        max_extra=2,
    )
    assert tag.count("+") == 2
    assert total["metal"] == 100 + 120 + 144
    # ResearchCentre L3 time huge vs flight=1 → no stack
    techs3 = {11103: Tech(11103, 2, "on")}
    fat = {"metal": 10, "crystal": 0, "deut": 0}
    total2, tag2 = stack_lf_build_lookahead(
        techs3,
        cfg,
        seed_tid=11103,
        seed_cost=fat,
        seed_tag="LF#11103→3",
        seed_level=3,
        flight_one_way=1,
        eco_speed=1,
        robots=0,
        nanites=0,
        peek_cost=no_peek,
        max_extra=2,
    )
    assert total2 == fat and tag2 == "LF#11103→3"

    ttechs = {11202: Tech(11202, 2, "on")}
    tcfg = {"MaxResearchLevel": 6, "MaxTechs12": 8}
    ttotal, ttag = stack_lf_tech_lookahead(
        ttechs,
        tcfg,
        seed_tid=11202,
        seed_cost={"metal": 50, "crystal": 0, "deut": 0},
        seed_tag="LFtech#11202→3",
        seed_level=3,
        flight_one_way=10**9,
        eco_speed=1,
        peek_cost=no_peek,
        max_extra=2,
    )
    assert ttag.count("+") == 2
    assert ttotal["metal"] > 50
    print("transport_lookahead_lf ok")
