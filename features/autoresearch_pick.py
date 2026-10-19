"""E08 AutoResearch pick: TBot GetNextResearchToBuild (pure, no Page)."""
from __future__ import annotations

import math

from game import Tech

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


def label(tid: int) -> str:
    return LABELS.get(tid, NAMES.get(tid, str(tid)))


def lvl(techs: dict[int, Tech], tid: int) -> int:
    t = techs.get(tid)
    return t.level if t else 0


def next_level(techs: dict[int, Tech], tid: int) -> int:
    return lvl(techs, tid) + 1


def under_cap(tid: int, techs: dict[int, Tech], cfg: dict) -> bool:
    key = CAPS.get(tid)
    if not key:
        return False
    return next_level(techs, tid) <= int(cfg.get(key) or 0)


def price(tid: int, level: int) -> dict[str, int]:
    m, c, d, f = _COST[tid]
    mul = f ** (level - 1)
    return {"metal": int(m * mul), "crystal": int(c * mul), "deut": int(d * mul)}


def converted_deut(cost: dict[str, int]) -> int:
    return math.ceil(cost["metal"] / 2.5 + cost["crystal"] / 1.5 + cost["deut"])


def max_expos(astro: int) -> int:
    # ponytail: no Discoverer/Admiral bonus
    return int(math.sqrt(astro))


def eligible(tid: int, techs: dict[int, Tech], lab: int, cfg: dict) -> bool:
    if not under_cap(tid, techs, cfg):
        return False
    e, laser, ion = lvl(techs, ENERGY), lvl(techs, LASER), lvl(techs, ION)
    hyper, shield = lvl(techs, HYPER), lvl(techs, SHIELD)
    esp, impulse = lvl(techs, ESPIONAGE), lvl(techs, IMPULSE)
    comp = lvl(techs, COMPUTER)
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
        if not eligible(tid, techs, lab, cfg):
            return False
        if afford_techs is None:
            return True
        t = afford_techs.get(tid)
        return bool(t and t.status == "on")

    if cfg.get("OptimizeForStart", True):
        e, comb = lvl(techs, ENERGY), lvl(techs, COMBUSTION)
        esp, impulse = lvl(techs, ESPIONAGE), lvl(techs, IMPULSE)
        comp, shield = lvl(techs, COMPUTER), lvl(techs, SHIELD)
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
            lvl(techs, ASTRO) == 0
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
        and max_expos(lvl(techs, ASTRO)) + 1 > slots_total
        and ok(COMPUTER)
    ):
        return COMPUTER

    # ponytail: PrioritizeAstro/Plasma/Energy/IRN via DOIR/time — add with E05 DOIR
    cands: list[tuple[int, int]] = []
    for tid in RESEARCH_IDS:
        if not ok(tid):
            continue
        cands.append((tid, converted_deut(price(tid, next_level(techs, tid)))))
    if not cands:
        return None
    cands.sort(key=lambda t: t[1])
    return cands[0][0]


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
    picked = pick_next(mid, {**cfg, "OptimizeForStart": False}, lab=8)
    assert picked is not None
    assert converted_deut(price(picked, next_level(mid, picked))) == min(
        converted_deut(price(t, next_level(mid, t)))
        for t in RESEARCH_IDS
        if eligible(t, mid, 8, cfg)
    )
    assert pick_next(
        mid,
        {**cfg, "OptimizeForStart": False},
        lab=8,
        afford_techs={LASER: Tech(LASER, 10, "on")},
    ) == LASER
    assert max_expos(16) == 4
    print("autoresearch_pick ok")
