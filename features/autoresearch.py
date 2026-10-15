"""E08 AutoResearch: TBot GetNextResearchToBuild + Target (biggest lab fallback)."""
from __future__ import annotations

import math
import random
from typing import Any

from game import (
    Celestial,
    Tech,
    build_technology,
    building_queue,
    current_resources,
    open_component,
    parse_celestials,
    format_cost,
    parse_ogame_int,
    parse_slots,
    parse_technologies,
    peek_tech_costs,
    research_countdown,
    research_queue,
    resource_production_per_hour,
    secs_until_resources,
    switch_celestial,
)
from runtime import Worker

LAB = 31
ENERGY, LASER, ION, HYPER, PLASMA = 113, 120, 121, 114, 122
COMBUSTION, IMPULSE, HYPERDRIVE = 115, 117, 118
ESPIONAGE, COMPUTER, ASTRO, IRN = 106, 108, 124, 123
WEAPONS, SHIELD, ARMOUR = 109, 110, 111
GRAVITON = 199

RESEARCH_IDS = (
    ENERGY,
    LASER,
    ION,
    HYPER,
    PLASMA,
    COMBUSTION,
    IMPULSE,
    HYPERDRIVE,
    ESPIONAGE,
    COMPUTER,
    ASTRO,
    IRN,
    WEAPONS,
    SHIELD,
    ARMOUR,
)

CAPS = {
    ENERGY: "MaxEnergyTechnology",
    LASER: "MaxLaserTechnology",
    ION: "MaxIonTechnology",
    HYPER: "MaxHyperspaceTechnology",
    PLASMA: "MaxPlasmaTechnology",
    COMBUSTION: "MaxCombustionDrive",
    IMPULSE: "MaxImpulseDrive",
    HYPERDRIVE: "MaxHyperspaceDrive",
    ESPIONAGE: "MaxEspionageTechnology",
    COMPUTER: "MaxComputerTechnology",
    ASTRO: "MaxAstrophysics",
    IRN: "MaxIntergalacticResearchNetwork",
    WEAPONS: "MaxWeaponsTechnology",
    SHIELD: "MaxShieldingTechnology",
    ARMOUR: "MaxArmourTechnology",
}

NAMES = {
    ENERGY: "Energy",
    LASER: "Laser",
    ION: "Ion",
    HYPER: "Hyperspace",
    PLASMA: "Plasma",
    COMBUSTION: "Combustion",
    IMPULSE: "Impulse",
    HYPERDRIVE: "HyperDrive",
    ESPIONAGE: "Espionage",
    COMPUTER: "Computer",
    ASTRO: "Astrophysics",
    IRN: "IRN",
    WEAPONS: "Weapons",
    SHIELD: "Shielding",
    ARMOUR: "Armour",
    GRAVITON: "Graviton",
}

LABELS = {
    ENERGY: "tecnologia de energia",
    LASER: "tecnologia de laser",
    ION: "tecnologia de íons",
    HYPER: "tecnologia de hiperespaço",
    PLASMA: "tecnologia de plasma",
    COMBUSTION: "motor de combustão",
    IMPULSE: "motor de impulsão",
    HYPERDRIVE: "motor hiperespacial",
    ESPIONAGE: "tecnologia de espionagem",
    COMPUTER: "tecnologia de computadores",
    ASTRO: "astrofísica",
    IRN: "rede de pesquisa intergaláctica",
    WEAPONS: "tecnologia de armas",
    SHIELD: "tecnologia de escudo",
    ARMOUR: "tecnologia de blindagem",
    GRAVITON: "tecnologia de graviton",
}

# base metal, crystal, deut, factor (level cost = base * factor**(level-1))
_COST = {
    ESPIONAGE: (200, 1000, 200, 2.0),
    COMPUTER: (0, 400, 600, 2.0),
    WEAPONS: (800, 200, 0, 2.0),
    SHIELD: (200, 600, 0, 2.0),
    ARMOUR: (1000, 0, 0, 2.0),
    ENERGY: (0, 800, 400, 2.0),
    HYPER: (0, 4000, 2000, 2.0),
    COMBUSTION: (400, 0, 600, 2.0),
    IMPULSE: (2000, 4000, 600, 2.0),
    HYPERDRIVE: (10000, 20000, 6000, 2.0),
    LASER: (200, 100, 0, 2.0),
    ION: (1000, 300, 100, 2.0),
    PLASMA: (2000, 4000, 1000, 2.0),
    IRN: (240000, 400000, 160000, 2.0),
    ASTRO: (4000, 8000, 4000, 1.75),
}


def _label(tid: int) -> str:
    return LABELS.get(tid, NAMES.get(tid, str(tid)))


def _lvl(techs: dict[int, Tech], tid: int) -> int:
    t = techs.get(tid)
    return t.level if t else 0


def _next(techs: dict[int, Tech], tid: int) -> int:
    return _lvl(techs, tid) + 1


def _under_cap(tid: int, techs: dict[int, Tech], cfg: dict) -> bool:
    key = CAPS.get(tid)
    if not key:
        return False
    return _next(techs, tid) <= int(cfg.get(key) or 0)


def _price(tid: int, level: int) -> dict[str, int]:
    m, c, d, f = _COST[tid]
    mul = f ** (level - 1)
    return {"metal": int(m * mul), "crystal": int(c * mul), "deut": int(d * mul)}


def _converted_deut(cost: dict[str, int]) -> int:
    # TBot Resources.GetConvertedDeuterium
    return math.ceil(cost["metal"] / 2.5 + cost["crystal"] / 1.5 + cost["deut"])


def _max_expos(astro: int) -> int:
    # ponytail: no Discoverer/Admiral bonus
    return int(math.sqrt(astro))


def _eligible(tid: int, techs: dict[int, Tech], lab: int, cfg: dict) -> bool:
    if not _under_cap(tid, techs, cfg):
        return False
    e, laser, ion = _lvl(techs, ENERGY), _lvl(techs, LASER), _lvl(techs, ION)
    hyper, shield = _lvl(techs, HYPER), _lvl(techs, SHIELD)
    esp, impulse = _lvl(techs, ESPIONAGE), _lvl(techs, IMPULSE)
    comp = _lvl(techs, COMPUTER)
    if tid == ENERGY:
        return lab >= 1
    if tid == LASER:
        return lab >= 1 and e >= 2
    if tid == ION:
        return lab >= 4 and e >= 4 and laser >= 5
    if tid == HYPER:
        return lab >= 7 and e >= 5 and shield >= 5
    if tid == PLASMA:
        return lab >= 4 and e >= 8 and laser >= 10 and ion >= 5
    if tid == COMBUSTION:
        return lab >= 1 and e >= 1
    if tid == IMPULSE:
        return lab >= 2 and e >= 1
    if tid == HYPERDRIVE:
        return lab >= 7 and hyper >= 3
    if tid == ESPIONAGE:
        return lab >= 3
    if tid == COMPUTER:
        return lab >= 1
    if tid == ASTRO:
        return lab >= 3 and esp >= 4 and impulse >= 3
    if tid == IRN:
        return lab >= 10 and comp >= 8 and hyper >= 8
    if tid == WEAPONS:
        return lab >= 4
    if tid == SHIELD:
        return lab >= 6 and e >= 3
    if tid == ARMOUR:
        return lab >= 2
    return False


def pick_next(
    techs: dict[int, Tech],
    cfg: dict,
    lab: int,
    *,
    slots_total: int = 0,
    prioritize_robots: bool = False,
    afford_techs: dict[int, Tech] | None = None,
) -> int | None:
    """TBot GetNextResearchToBuild. afford_techs filters status=on when set."""

    def ok(tid: int) -> bool:
        if not _eligible(tid, techs, lab, cfg):
            return False
        if afford_techs is None:
            return True
        t = afford_techs.get(tid)
        return bool(t and t.status == "on")

    if cfg.get("OptimizeForStart", True):
        e, comb = _lvl(techs, ENERGY), _lvl(techs, COMBUSTION)
        esp, impulse = _lvl(techs, ESPIONAGE), _lvl(techs, IMPULSE)
        comp, shield = _lvl(techs, COMPUTER), _lvl(techs, SHIELD)
        if e == 0 and lab > 0 and ok(ENERGY):
            return ENERGY
        if comb < 2 and lab > 0 and e >= 1 and ok(COMBUSTION):
            return COMBUSTION
        if esp < 4 and lab >= 3 and ok(ESPIONAGE):
            return ESPIONAGE
        if impulse < 3 and lab >= 2 and e >= 1 and ok(IMPULSE):
            return IMPULSE
        if comp < 1 and lab >= 1 and ok(COMPUTER):
            return COMPUTER
        if (
            _lvl(techs, ASTRO) == 0
            and lab >= 3
            and esp >= 4
            and impulse >= 3
            and ok(ASTRO)
        ):
            return ASTRO
        if 1 <= e < 3 and lab > 0 and ok(ENERGY):
            return ENERGY
        if shield < 2 and lab > 5 and e >= 3 and ok(SHIELD):
            return SHIELD
        if 2 <= comb < 6 and lab > 0 and e >= 1 and ok(COMBUSTION):
            return COMBUSTION
        if prioritize_robots and comp < 10 and lab >= 1 and ok(COMPUTER):
            return COMPUTER

    if (
        cfg.get("EnsureExpoSlots", True)
        and slots_total > 0
        and _max_expos(_lvl(techs, ASTRO)) + 1 > slots_total
        and ok(COMPUTER)
    ):
        return COMPUTER

    # ponytail: PrioritizeAstro/Plasma/Energy/IRN via DOIR/time — add with E05 DOIR
    cands: list[tuple[int, int]] = []
    for tid in RESEARCH_IDS:
        if not ok(tid):
            continue
        cands.append((tid, _converted_deut(_price(tid, _next(techs, tid)))))
    if not cands:
        return None
    cands.sort(key=lambda t: t[1])
    return cands[0][0]


def _match_target(c: Celestial, target: dict) -> bool:
    if not target:
        return False
    return (
        int(target.get("Galaxy", -1)) == c.coords.galaxy
        and int(target.get("System", -1)) == c.coords.system
        and int(target.get("Position", -1)) == c.coords.position
        and (target.get("Type") or "Planet") == c.coords.type
    )


def resolve_target(page, cfg: dict) -> tuple[Celestial | None, int, str]:
    """(celestial, lab_level, why). Biggest lab if Target missing/invalid."""
    celestials = [c for c in parse_celestials(page) if c.coords.type == "Planet"]
    if not celestials:
        return None, 0, "sem planetas"

    target = cfg.get("Target") or {}
    hit = next((c for c in celestials if _match_target(c, target)), None)
    if hit is not None:
        switch_celestial(page, hit)
        open_component(page, "facilities")
        lab = _lvl(parse_technologies(page), LAB)
        return hit, lab, "Target"

    best: Celestial | None = None
    best_lab = -1
    for c in celestials:
        switch_celestial(page, c)
        open_component(page, "facilities")
        lab = _lvl(parse_technologies(page), LAB)
        if lab > best_lab:
            best, best_lab = c, lab
    return best, best_lab, "maior lab"


_fmt_cost = format_cost


def _wait_for_resources(
    page, tid: int, cap_s: float, next_lvl: int | str
) -> tuple[float | None, str, str]:
    if "component=research" not in page.url:
        open_component(page, "research")
    lab = _label(tid)
    cost = peek_tech_costs(page, tid)
    if not cost:
        return None, "custo indisponível", (
            f"quer {lab} → {next_lvl} mas custo indisponível na UI"
        )
    res = current_resources(page)
    have = {
        "metal": parse_ogame_int(res["metal"]),
        "crystal": parse_ogame_int(res["crystal"]),
        "deut": parse_ogame_int(res["deut"]),
    }
    prod = resource_production_per_hour(page)
    eta = secs_until_resources(cost, have, prod)
    stock = f"tem M{have['metal']} C{have['crystal']} D{have['deut']}"
    ph = (
        f"prod/h M{prod.get('metal', 0)} "
        f"C{prod.get('crystal', 0)} D{prod.get('deut', 0)}"
    )
    if eta is None:
        return None, "sem ETA", (
            f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; "
            f"{stock}; {ph}; produção insuficiente p/ ETA)"
        )
    jitter = random.uniform(5, 20)
    raw = eta + jitter
    if raw > cap_s:
        return (
            cap_s,
            f"ETA {eta:.0f}s capado em {cap_s:.0f}s",
            f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; "
            f"{stock}; {ph}; ETA {eta:.0f}s → espera cap {cap_s:.0f}s)",
        )
    return (
        raw,
        f"ETA {eta:.0f}s +folga",
        f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; "
        f"{stock}; {ph}; ETA {eta:.0f}s)",
    )


def research_once(
    page,
    cfg: dict,
    interval_max_s: float,
    *,
    prioritize_robots: bool = False,
    book=None,
) -> tuple[str | None, float | None, str | None, str]:
    """(msg, wait_s, schedule_why, log_line). wait None → CheckInterval."""
    celestial, lab, how = resolve_target(page, cfg)
    if celestial is None:
        return None, None, "sem planeta", "sem planeta alvo"
    tag = celestial.label

    if lab <= 0:
        return None, None, "sem lab", f"{tag}: Research Lab ausente ({how})"

    switch_celestial(page, celestial)
    open_component(page, "facilities")
    bid, bcd = building_queue(page)
    if bid == LAB:
        wait = bcd + random.uniform(5, 15) if bcd > 0 else random.uniform(5, 20)
        return (
            "lab busy",
            wait,
            f"lab upgrade {bcd:.0f}s",
            f"{tag}: lab em upgrade ({bcd:.0f}s)",
        )

    open_component(page, "research")
    rid, rcd = research_queue(page)
    if rid:
        wait = rcd + random.uniform(5, 15) if rcd > 0 else random.uniform(5, 20)
        return (
            "busy",
            wait,
            f"pesquisa {rcd:.0f}s",
            f"{tag}: pesquisa em andamento ({rcd:.0f}s)",
        )

    techs = parse_technologies(page)
    slots = parse_slots(page)
    tid = pick_next(
        techs,
        cfg,
        lab,
        slots_total=slots.total,
        prioritize_robots=prioritize_robots,
        afford_techs=techs,
    )
    if tid is None:
        want = pick_next(
            techs,
            cfg,
            lab,
            slots_total=slots.total,
            prioritize_robots=prioritize_robots,
        )
        if want is None:
            return None, None, "nada sob cap", f"{tag}: nada sob cap / elegível"
        nxt = _next(techs, want)
        wait, sched, detail = _wait_for_resources(page, want, interval_max_s, nxt)
        return (
            f"wait {NAMES.get(want, want)}",
            wait,
            sched,
            f"{tag}: {detail}",
        )

    cost = peek_tech_costs(page, tid) or _price(tid, _next(techs, tid))
    cur = _lvl(techs, tid)
    nxt = cur + 1
    lab_name = _label(tid)
    fail = build_technology(page, tid)
    if fail:
        return (
            f"fail {NAMES.get(tid, tid)}",
            90.0,
            "retry 90s",
            f"{tag}: recursos ok p/ {lab_name} {cur}→{nxt}, mas click falhou "
            f"({fail}) — retry 90s",
        )
    if book is not None and cost:
        book.spend(celestial.id, cost)
    cd = research_countdown(page)
    if cd > 0:
        wait = cd + random.uniform(5, 15)
        sched = f"countdown {cd:.0f}s"
    else:
        wait = random.uniform(20, 45)
        sched = "pós-research 20–45s"
    return (
        f"{NAMES.get(tid, tid)}→{nxt}",
        wait,
        sched,
        f"{tag}: recursos disponíveis, {lab_name} {cur}→{nxt} "
        f"({_fmt_cost(cost)}) [{how}]",
    )


class AutoResearchWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        brain = settings.get("Brain") or {}
        cfg = brain.get("AutoResearch") or {}
        if not brain.get("Active") or not cfg.get("Active"):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        am = brain.get("AutoMine") or {}
        prioritize_robots = bool(am.get("PrioritizeRobotsAndNanites"))
        tui = ctx.get("tui")
        refresh = ctx.get("refresh")
        lo_m, hi_m = self.interval_min / 60, self.interval_max / 60

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        try:
            result, wait, why, line = research_once(
                page,
                cfg,
                self.interval_max,
                prioritize_robots=prioritize_robots,
                book=ctx.get("resources"),
            )
        except Exception as e:
            err = str(e).split("\n", 1)[0][:100]
            _log(f"autoresearch: erro UI ({err}) — retry 90s", "warn")
            self._next_wait = 90.0
            self.reason = "erro UI"
            return "erro UI"

        lvl = "ok" if result and "→" in (result or "") else "info"
        if result and str(result).startswith("fail"):
            lvl = "warn"
        _log(f"autoresearch: {line}", lvl)

        if wait is not None and why:
            self._next_wait = wait
            self.reason = why
            _log(f"autoresearch: próxima decisão em {wait:.0f}s — {why}")
        else:
            wait_s = random.uniform(self.interval_min, self.interval_max)
            self._next_wait = wait_s
            self.reason = f"nada urgente (CheckInterval {lo_m:.0f}–{hi_m:.0f}min)"
            _log(f"autoresearch: próxima decisão em {wait_s:.0f}s — {self.reason}")

        if result and "→" in result:
            return result
        if result:
            return str(result)
        return "nada"


if __name__ == "__main__":
    techs = {
        ENERGY: Tech(ENERGY, 0, "on"),
        COMBUSTION: Tech(COMBUSTION, 0, "disabled"),
        ESPIONAGE: Tech(ESPIONAGE, 0, "off"),
        IMPULSE: Tech(IMPULSE, 0, "off"),
        COMPUTER: Tech(COMPUTER, 0, "off"),
        ASTRO: Tech(ASTRO, 0, "off"),
        SHIELD: Tech(SHIELD, 0, "off"),
    }
    cfg = {
        "OptimizeForStart": True,
        "EnsureExpoSlots": True,
        "MaxEnergyTechnology": 20,
        "MaxLaserTechnology": 12,
        "MaxIonTechnology": 5,
        "MaxHyperspaceTechnology": 20,
        "MaxPlasmaTechnology": 20,
        "MaxCombustionDrive": 19,
        "MaxImpulseDrive": 17,
        "MaxHyperspaceDrive": 15,
        "MaxEspionageTechnology": 8,
        "MaxComputerTechnology": 20,
        "MaxAstrophysics": 23,
        "MaxIntergalacticResearchNetwork": 12,
        "MaxWeaponsTechnology": 25,
        "MaxShieldingTechnology": 25,
        "MaxArmourTechnology": 25,
    }
    assert pick_next(techs, cfg, lab=1) == ENERGY
    techs[ENERGY] = Tech(ENERGY, 1, "on")
    assert pick_next(techs, cfg, lab=1) == COMBUSTION
    techs[COMBUSTION] = Tech(COMBUSTION, 2, "on")
    techs[ESPIONAGE] = Tech(ESPIONAGE, 3, "on")
    assert pick_next(techs, cfg, lab=3) == ESPIONAGE
    techs[ESPIONAGE] = Tech(ESPIONAGE, 4, "on")
    techs[IMPULSE] = Tech(IMPULSE, 2, "on")
    assert pick_next(techs, cfg, lab=2) == IMPULSE
    techs[IMPULSE] = Tech(IMPULSE, 3, "on")
    assert pick_next(techs, cfg, lab=3) == COMPUTER
    techs[COMPUTER] = Tech(COMPUTER, 1, "on")
    assert pick_next(techs, cfg, lab=3) == ASTRO
    mid = {
        ENERGY: Tech(ENERGY, 8, "on"),
        LASER: Tech(LASER, 10, "on"),
        ION: Tech(ION, 5, "on"),
        HYPER: Tech(HYPER, 5, "disabled"),
        PLASMA: Tech(PLASMA, 0, "on"),
        COMBUSTION: Tech(COMBUSTION, 6, "on"),
        IMPULSE: Tech(IMPULSE, 5, "on"),
        HYPERDRIVE: Tech(HYPERDRIVE, 0, "off"),
        ESPIONAGE: Tech(ESPIONAGE, 4, "on"),
        COMPUTER: Tech(COMPUTER, 5, "on"),
        ASTRO: Tech(ASTRO, 1, "on"),
        IRN: Tech(IRN, 0, "off"),
        WEAPONS: Tech(WEAPONS, 0, "on"),
        SHIELD: Tech(SHIELD, 5, "on"),
        ARMOUR: Tech(ARMOUR, 0, "on"),
    }
    # cheapest under caps among eligible → Laser next or Weapons/Armour etc.
    picked = pick_next(mid, {**cfg, "OptimizeForStart": False}, lab=8)
    assert picked is not None
    assert _converted_deut(_price(picked, _next(mid, picked))) == min(
        _converted_deut(_price(t, _next(mid, t)))
        for t in RESEARCH_IDS
        if _eligible(t, mid, 8, cfg)
    )
    assert pick_next(
        mid,
        {**cfg, "OptimizeForStart": False},
        lab=8,
        afford_techs={LASER: Tech(LASER, 10, "on")},
    ) == LASER
    assert _max_expos(16) == 4
    assert secs_until_resources(
        {"metal": 1000, "crystal": 0, "deut": 0},
        {"metal": 0, "crystal": 0, "deut": 0},
        {"metal": 3600, "crystal": 0, "deut": 0},
    ) == 1000
    print("autoresearch ok")
