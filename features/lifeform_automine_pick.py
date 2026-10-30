"""Lifeform AutoMine pick puro (caps / food-pop / ConvertedDeut) — sem Page."""
from __future__ import annotations

import math

from game import Celestial, Population, Tech

# slot → settings key (same for all races; id % 100 = slot 1..12)
SLOT_CAPS = {
    1: "MaxBasePopulationBuilding",
    2: "MaxBaseFoodBuilding",
    3: "MaxBaseTechBuilding",
    4: "MaxT2Building",
    5: "MaxT3Building",
    6: "MaxBuilding6",
    7: "MaxBuilding7",
    8: "MaxBuilding8",
    9: "MaxBuilding9",
    10: "MaxBuilding10",
    11: "MaxBuilding11",
    12: "MaxBuilding12",
}


def is_lf_building(tid: int) -> bool:
    slot = tid % 100
    return 1 <= slot <= 12 and tid // 100 in (111, 121, 131, 141)


def slot_of(tid: int) -> int:
    return tid % 100


def under_cap(tid: int, level: int, cfg: dict) -> bool:
    key = SLOT_CAPS.get(slot_of(tid))
    if not key:
        return False
    return level < int(cfg.get(key) or 0)


def converted_deut(cost: dict[str, int]) -> int:
    return int(
        math.ceil(
            cost.get("metal", 0) / 2.5
            + cost.get("crystal", 0) / 1.5
            + cost.get("deut", 0)
        )
    )


def lf_beats_mine(lf_cost: dict[str, int], mine_cost: dict[str, int]) -> bool:
    """True if LF upgrade ConvertedDeut > next classic mine (TB-05 / TBot)."""
    return converted_deut(lf_cost) > converted_deut(mine_cost)


def excluded(c: Celestial, exclude: list) -> bool:
    for e in exclude or []:
        if (
            int(e.get("Galaxy", -1)) == c.coords.galaxy
            and int(e.get("System", -1)) == c.coords.system
            and int(e.get("Position", -1)) == c.coords.position
            and (e.get("Type") or "Planet") == c.coords.type
        ):
            return True
    return False


def _slot_tech(techs: dict[int, Tech], slot: int) -> Tech | None:
    for t in techs.values():
        if is_lf_building(t.id) and slot_of(t.id) == slot:
            return t
    return None


def _cand_ok(
    t: Tech,
    cfg: dict,
    *,
    afford: bool,
    prevent_tech: bool,
    min_level: int = 1,
) -> bool:
    if not is_lf_building(t.id) or t.level < min_level:
        return False
    if not under_cap(t.id, t.level, cfg):
        return False
    if prevent_tech and slot_of(t.id) == 3:
        return False
    if afford:
        return t.status == "on"
    return t.status in ("on", "disabled")


def pick_next(
    techs: dict[int, Tech],
    cfg: dict,
    *,
    afford: bool = True,
    prevent_tech: bool = False,
    pop: Population | None = None,
    energy: int = 0,
) -> int | None:
    """E06-T03: food/pop/T2/T3 priorities (TBot), else cheapest ≥1 by level."""

    def try_slot(slot: int, *, min_level: int = 0) -> int | None:
        t = _slot_tech(techs, slot)
        if t is None:
            return None
        if _cand_ok(
            t, cfg, afford=afford, prevent_tech=prevent_tech, min_level=min_level
        ):
            return t.id
        return None

    if pop is not None:
        # food (slot 2) when starving / will starve; skip if no energy headroom
        if (pop.is_starving() or pop.will_starve()) and energy >= 0:
            hit = try_slot(2)
            if hit is not None:
                return hit
        if pop.food_for_more() or pop.is_full():
            hit = try_slot(1)
            if hit is not None:
                return hit
        if pop.needs_more_t2():
            hit = try_slot(4)
            if hit is not None:
                return hit
        if pop.needs_more_t3():
            hit = try_slot(5)
            if hit is not None:
                return hit

    cands = [
        t
        for t in techs.values()
        if _cand_ok(t, cfg, afford=afford, prevent_tech=prevent_tech, min_level=1)
    ]
    if not cands:
        return None
    # ponytail: level asc instead of ConvertedDeuterium; peek-all when ROI matters
    return min(cands, key=lambda t: (t.level, slot_of(t.id))).id


if __name__ == "__main__":
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
    techs = {
        11101: Tech(11101, 10, "on"),
        11102: Tech(11102, 8, "on"),
        11103: Tech(11103, 2, "disabled"),
        11106: Tech(11106, 0, "on"),  # level 0 → skip
    }
    assert pick_next(techs, cfg) == 11102  # lower level among ≥1 on
    assert pick_next(techs, cfg, afford=False) == 11103
    assert pick_next(techs, cfg, prevent_tech=True, afford=False) == 11102
    assert under_cap(11101, 59, cfg)
    assert not under_cap(11101, 60, cfg)
    assert converted_deut({"metal": 250, "crystal": 150, "deut": 10}) == 210
    assert is_lf_building(11101) and not is_lf_building(1)
    cheap_mine = {"metal": 100, "crystal": 50, "deut": 0}
    pricey_lf = {"metal": 5_000, "crystal": 2_000, "deut": 500}
    assert lf_beats_mine(pricey_lf, cheap_mine)
    assert not lf_beats_mine(cheap_mine, pricey_lf)
    # E06-T03: starving → food (slot 2) even if higher level than others
    starving = Population(available=500, satisfied=100, living_space=900, hungry=12)
    assert pick_next(techs, cfg, pop=starving, energy=10) == 11102
    # food for more (and not will_starve) → population (slot 1)
    feed = Population(available=210, satisfied=590, living_space=500)
    assert pick_next(techs, cfg, pop=feed, energy=10) == 11101
    # T2: pop at cap so is_full doesn't steal; food not needed
    techs[11104] = Tech(11104, 1, "on")
    need_t2 = Population(
        available=200, satisfied=200, living_space=200, t2=0, hungry=0
    )
    cfg_pop_cap = {**cfg, "MaxBasePopulationBuilding": 10}  # 11101 lvl10 → capped
    assert pick_next(techs, cfg_pop_cap, pop=need_t2, energy=10) == 11104
    print("lifeform_automine_pick ok")
