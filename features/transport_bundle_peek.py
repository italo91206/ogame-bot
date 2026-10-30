"""Peeks de slots idle p/ E04-T05 bundle (+ razões de omit p/ filelog)."""
from __future__ import annotations

from game import (
    Celestial,
    building_queue,
    current_resources,
    lf_building_queue,
    lf_research_queue,
    parse_ogame_int,
    parse_population,
    parse_slots,
    peek_tech_costs,
    research_queue,
)

from features.transport_bundle import (
    CelTechCache,
    KIND_CLASSIC,
    KIND_LF_BUILD,
    KIND_LF_TECH,
    KIND_RESEARCH,
    note_reason,
)


def _feat_transport_on(brain: dict, key: str) -> bool:
    from features.transports import transports_enabled

    cfg = brain.get(key) or {}
    return bool(cfg.get("Active") and transports_enabled(brain, cfg))


def _pad_moon_deut(cost: dict[str, int], am_cfg: dict, moon: bool) -> dict[str, int]:
    if not cost or not moon:
        return dict(cost) if cost else {}
    leave = int(am_cfg.get("DeutToLeaveOnMoons") or 0)
    if leave <= 0:
        return dict(cost)
    out = {k: int(cost.get(k) or 0) for k in ("metal", "crystal", "deut")}
    out["deut"] += leave
    return out


def classic_next(
    page, brain: dict, moon: bool, cache: CelTechCache, reasons: list[str] | None = None
) -> tuple[int, dict[str, int], str] | None:
    """(tid, cost, tag) for next classic build; skip SAT / busy queue."""
    from features.automine_pick import FACILITY_IDS, SAT_ID, label, pick_next

    if not _feat_transport_on(brain, "AutoMine"):
        note_reason(reasons, "omit classic=off")
        return None
    if building_queue(page)[0]:
        note_reason(reasons, "omit classic=fila")
        return None
    am = brain.get("AutoMine") or {}
    if moon:
        techs = dict(cache.techs("facilities"))
    else:
        techs = dict(cache.techs("supplies"))
        techs.update(cache.techs("facilities"))
    energy = parse_ogame_int(current_resources(page).get("energy", "0"))
    tid = pick_next(techs, am, moon, energy, afford=False)
    if tid is None or tid == SAT_ID:
        note_reason(reasons, "omit classic=sats" if tid == SAT_ID else "omit classic=pick")
        return None
    need = "facilities" if (moon or tid in FACILITY_IDS) else "supplies"
    cache.techs(need)
    cost = _pad_moon_deut(peek_tech_costs(page, tid) or {}, am, moon)
    if not cost or sum(cost.values()) <= 0:
        note_reason(reasons, "omit classic=custo")
        return None
    nxt = (techs[tid].level + 1) if tid in techs else "?"
    tag = f"{label(tid)}→{nxt}"
    note_reason(reasons, f"+{KIND_CLASSIC} {tag}")
    return tid, cost, tag


def lf_build_next(
    page,
    brain: dict,
    *,
    block_lf: bool,
    cache: CelTechCache,
    reasons: list[str] | None = None,
) -> tuple[int, dict[str, int], str] | None:
    from features.lifeform_automine_pick import pick_next

    if block_lf:
        note_reason(reasons, "omit lf_build=robots")
        return None
    if not _feat_transport_on(brain, "LifeformAutoMine"):
        note_reason(reasons, "omit lf_build=off")
        return None
    if lf_building_queue(page)[0]:
        note_reason(reasons, "omit lf_build=fila")
        return None
    cfg = brain.get("LifeformAutoMine") or {}
    supplies = cache.techs("supplies")
    crystal_lvl = supplies[2].level if 2 in supplies else 0
    gate = int(cfg.get("StartFromCrystalMineLvl") or 0)
    if crystal_lvl < gate:
        note_reason(reasons, f"omit lf_build=crystal<{gate}")
        return None
    techs = cache.techs("lfbuildings")
    pop = parse_population(page)
    energy = parse_ogame_int(current_resources(page).get("energy", "0"))
    prevent_tech = lf_research_queue(page)[0] != 0
    tid = pick_next(
        techs, cfg, afford=False, prevent_tech=prevent_tech, pop=pop, energy=energy
    )
    if tid is None:
        note_reason(reasons, "omit lf_build=pick")
        return None
    cost = peek_tech_costs(page, tid) or {}
    if not cost or sum(cost.values()) <= 0:
        note_reason(reasons, "omit lf_build=custo")
        return None
    if cfg.get("PreventIfMoreExpensiveThanNextMine"):
        from features.lifeform_automine import mine_too_cheap

        if mine_too_cheap(page, cost, techs=supplies):
            note_reason(reasons, "omit lf_build=prevent")
            return None
    tag = f"LF#{tid}→{techs[tid].level + 1}"
    note_reason(reasons, f"+{KIND_LF_BUILD} {tag}")
    return tid, cost, tag


def lf_tech_next(
    page, brain: dict, cache: CelTechCache, reasons: list[str] | None = None
) -> tuple[int, dict[str, int], str] | None:
    from features.lifeform_autoresearch_pick import pick_next

    if not _feat_transport_on(brain, "LifeformAutoResearch"):
        note_reason(reasons, "omit lf_tech=off")
        return None
    if lf_research_queue(page)[0]:
        note_reason(reasons, "omit lf_tech=fila")
        return None
    cfg = brain.get("LifeformAutoResearch") or {}
    techs = cache.techs("lfresearch")
    tid = pick_next(techs, cfg, afford=False)
    if tid is None:
        note_reason(reasons, "omit lf_tech=pick")
        return None
    cost = peek_tech_costs(page, tid) or {}
    if not cost or sum(cost.values()) <= 0:
        note_reason(reasons, "omit lf_tech=custo")
        return None
    tag = f"LFtech#{tid}→{techs[tid].level + 1}"
    note_reason(reasons, f"+{KIND_LF_TECH} {tag}")
    return tid, cost, tag


def dest_is_ar_target(celestial: Celestial, cfg: dict) -> bool:
    """TB-04: só peeka research se Target fixo aponta p/ dest (não 'maior lab')."""
    t = cfg.get("Target") or {}
    if not t:
        return False
    return (
        int(t.get("Galaxy", -1)) == celestial.coords.galaxy
        and int(t.get("System", -1)) == celestial.coords.system
        and int(t.get("Position", -1)) == celestial.coords.position
        and (t.get("Type") or "Planet") == celestial.coords.type
    )


def research_next(
    page,
    brain: dict,
    celestial: Celestial,
    cache: CelTechCache,
    reasons: list[str] | None = None,
) -> tuple[dict[str, int], str] | None:
    from features.autoresearch_pick import LAB, label, pick_next, price

    if not _feat_transport_on(brain, "AutoResearch"):
        note_reason(reasons, "omit research=off")
        return None
    cfg = brain.get("AutoResearch") or {}
    if not (cfg.get("Target") or {}):
        note_reason(reasons, "omit research=Target vazio")
        return None
    if not dest_is_ar_target(celestial, cfg):
        note_reason(reasons, "omit research=Target≠dest")
        return None
    if research_queue(page)[0]:
        note_reason(reasons, "omit research=fila")
        return None
    bid, _ = building_queue(page)
    if bid == LAB:
        note_reason(reasons, "omit research=lab fila")
        return None
    fac = cache.techs("facilities")
    lab = fac[LAB].level if LAB in fac else 0
    if lab <= 0:
        note_reason(reasons, "omit research=lab0")
        return None
    techs = cache.techs("research")
    slots = parse_slots(page)
    am = brain.get("AutoMine") or {}
    tid = pick_next(
        techs,
        cfg,
        lab,
        slots_total=slots.total,
        prioritize_robots=bool(am.get("PrioritizeRobotsAndNanites")),
    )
    if tid is None:
        note_reason(reasons, "omit research=pick")
        return None
    nxt = techs[tid].level + 1 if tid in techs else 1
    cost = peek_tech_costs(page, tid) or price(tid, nxt)
    if not cost or sum(cost.values()) <= 0:
        note_reason(reasons, "omit research=custo")
        return None
    tag = f"{label(tid)}→{nxt}"
    note_reason(reasons, f"+{KIND_RESEARCH} {tag}")
    return cost, tag
