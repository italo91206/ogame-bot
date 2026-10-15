"""AutoMine pick puro (caps / energia / sats count) — sem Page."""
from __future__ import annotations

import math
import re
from html import unescape

from game import Celestial, Tech

METAL, CRYSTAL, DEUT, SOLAR, FUSION = 1, 2, 3, 4, 12
METAL_STOR, CRYS_STOR, DEUT_TANK = 22, 23, 24
ROBOTS, SHIPYARD, LAB, SILO = 14, 21, 31, 44
NANITES, TERRA, DOCK = 15, 33, 36
LUNAR_BASE, PHALANX, JUMPGATE = 41, 42, 43
SAT_ID = 212

SUPPLY_IDS = {METAL, CRYSTAL, DEUT, SOLAR, FUSION, METAL_STOR, CRYS_STOR, DEUT_TANK}
FACILITY_IDS = {ROBOTS, SHIPYARD, LAB, SILO, NANITES, TERRA, DOCK, LUNAR_BASE, PHALANX, JUMPGATE}

PLANET_CAPS = {
    METAL: "MaxMetalMine",
    CRYSTAL: "MaxCrystalMine",
    DEUT: "MaxDeuteriumSynthetizer",
    SOLAR: "MaxSolarPlant",
    FUSION: "MaxFusionReactor",
    METAL_STOR: "MaxMetalStorage",
    CRYS_STOR: "MaxCrystalStorage",
    DEUT_TANK: "MaxDeuteriumTank",
    ROBOTS: "MaxRoboticsFactory",
    SHIPYARD: "MaxShipyard",
    LAB: "MaxResearchLab",
    SILO: "MaxMissileSilo",
    NANITES: "MaxNaniteFactory",
    TERRA: "MaxTerraformer",
    DOCK: "MaxSpaceDock",
}
MOON_CAPS = {
    LUNAR_BASE: "MaxLunarBase",
    ROBOTS: "MaxLunarRoboticsFactory",
    SHIPYARD: "MaxLunarShipyard",
    PHALANX: "MaxSensorPhalanx",
    JUMPGATE: "MaxJumpGate",
}

NAMES = {
    METAL: "MetalMine",
    CRYSTAL: "CrystalMine",
    DEUT: "DeutSynth",
    SOLAR: "SolarPlant",
    FUSION: "Fusion",
    METAL_STOR: "MetalStorage",
    CRYS_STOR: "CrystalStorage",
    DEUT_TANK: "DeutTank",
    ROBOTS: "Robots",
    SHIPYARD: "Shipyard",
    LAB: "Lab",
    SILO: "Silo",
    NANITES: "Nanites",
    TERRA: "Terraformer",
    DOCK: "SpaceDock",
    LUNAR_BASE: "LunarBase",
    PHALANX: "Phalanx",
    JUMPGATE: "JumpGate",
    SAT_ID: "SolarSatellite",
}

LABELS = {
    METAL: "mina de metal",
    CRYSTAL: "mina de cristal",
    DEUT: "sintetizador de deutério",
    SOLAR: "planta de energia solar",
    FUSION: "reator de fusão",
    METAL_STOR: "armazém de metal",
    CRYS_STOR: "armazém de cristal",
    DEUT_TANK: "tanque de deutério",
    ROBOTS: "fábrica de robôs",
    SHIPYARD: "hangar",
    LAB: "lab de pesquisa",
    SILO: "silo de mísseis",
    NANITES: "fábrica de nanites",
    TERRA: "terraformador",
    DOCK: "doca espacial",
    LUNAR_BASE: "base lunar",
    PHALANX: "sensor phalanx",
    JUMPGATE: "portal de salto",
    SAT_ID: "satélites solares",
}


def label(tid: int) -> str:
    return LABELS.get(tid, NAMES.get(tid, str(tid)))


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


def under_cap(tid: int, level: int, cfg: dict, moon: bool) -> bool:
    key = (MOON_CAPS if moon else PLANET_CAPS).get(tid)
    if not key:
        return False
    return level < int(cfg.get(key) or 0)


def sat_output(avg_temp: float) -> int:
    # ponytail: sem bônus Collector/Engineer; add when staff parsing exists
    return max(1, int(round((avg_temp + 160) / 6.0)))


def needed_sats(energy: int, avg_temp: float) -> int:
    if energy >= 0:
        return 0
    return int(math.ceil(abs(energy) / float(sat_output(avg_temp))))


def avg_temp_from_title(title: str) -> float:
    nums = [int(x) for x in re.findall(r"(-?\d+)\s*°\s*C", unescape(title or ""))]
    if len(nums) >= 2:
        return (nums[0] + nums[1]) / 2.0
    return 0.0


def pick_next(
    techs: dict[int, Tech],
    cfg: dict,
    moon: bool,
    energy: int,
    *,
    afford: bool = True,
) -> int | None:
    """Priority pick under cap. afford=True → status=on only; False → on|disabled."""

    def ok(tid: int) -> bool:
        t = techs.get(tid)
        if not t or not under_cap(tid, t.level, cfg, moon):
            return False
        if afford:
            return t.status == "on"
        return t.status in ("on", "disabled")

    if moon:
        for tid in (LUNAR_BASE, ROBOTS, JUMPGATE, PHALANX, SHIPYARD):
            if ok(tid):
                return tid
        return None

    if energy < 0:
        for tid in (SOLAR, FUSION):
            if ok(tid):
                return tid
        if cfg.get("BuildSolarSatellites", True):
            sy = techs.get(SHIPYARD)
            if sy and sy.level >= 1:
                return SAT_ID
            for tid in (SHIPYARD, ROBOTS):
                if ok(tid):
                    return tid
        return None

    if cfg.get("PrioritizeRobotsAndNanites"):
        for tid in (ROBOTS, NANITES):
            if ok(tid):
                return tid

    # ponytail: start ratio instead of DOIR; upgrade when MaxDaysOfInvestmentReturn needed
    if cfg.get("OptimizeForStart", True):
        m = techs[METAL].level if METAL in techs else 0
        c = techs[CRYSTAL].level if CRYSTAL in techs else 0
        d = techs[DEUT].level if DEUT in techs else 0
        if m < 10 or c < 7 or d < 5:
            if m <= c + 2 and ok(METAL):
                return METAL
            if c <= d + 2 and ok(CRYSTAL):
                return CRYSTAL
            if ok(DEUT):
                return DEUT

    mines = [techs[t] for t in (METAL, CRYSTAL, DEUT) if ok(t)]
    if mines:
        return min(mines, key=lambda t: t.level).id

    if cfg.get("BuildDepositIfFull"):
        for tid in (DEUT_TANK, CRYS_STOR, METAL_STOR):
            if ok(tid):
                return tid

    for tid in (ROBOTS, NANITES, SHIPYARD, LAB, SILO, TERRA, DOCK):
        if ok(tid):
            return tid
    return None


def pick_why(
    tid: int, techs: dict[int, Tech], cfg: dict, moon: bool, energy: int
) -> str:
    if moon:
        return "prioridade lua"
    if energy < 0 and tid == SAT_ID:
        return f"energia {energy} → sats"
    if energy < 0 and tid in (SOLAR, FUSION, SHIPYARD, ROBOTS):
        return f"energia {energy}"
    if cfg.get("PrioritizeRobotsAndNanites") and tid in (ROBOTS, NANITES):
        return "PrioritizeRobotsAndNanites"
    if cfg.get("OptimizeForStart", True) and tid in (METAL, CRYSTAL, DEUT):
        m = techs[METAL].level if METAL in techs else 0
        c = techs[CRYSTAL].level if CRYSTAL in techs else 0
        d = techs[DEUT].level if DEUT in techs else 0
        if m < 10 or c < 7 or d < 5:
            return f"OptimizeForStart M{m}/C{c}/D{d}"
    if tid in (METAL, CRYSTAL, DEUT):
        return "mina mais baixa sob cap"
    if tid in (DEUT_TANK, CRYS_STOR, METAL_STOR):
        return "BuildDepositIfFull"
    return "facility sob cap"


if __name__ == "__main__":
    assert sat_output(0) == 27
    assert needed_sats(-100, 0) == 4
    assert needed_sats(10, 0) == 0
    assert avg_temp_from_title("-11°C to 29°C") == 9.0
    techs = {
        METAL: Tech(METAL, 12, "on"),
        CRYSTAL: Tech(CRYSTAL, 10, "on"),
        DEUT: Tech(DEUT, 8, "on"),
        SOLAR: Tech(SOLAR, 20, "on"),
        SHIPYARD: Tech(SHIPYARD, 2, "on"),
    }
    cfg = {
        "BuildSolarSatellites": True,
        "MaxSolarPlant": 20,
        "MaxFusionReactor": 0,
        "MaxShipyard": 12,
        "MaxRoboticsFactory": 10,
        "MaxMetalMine": 40,
        "MaxCrystalMine": 35,
        "MaxDeuteriumSynthetizer": 37,
    }
    assert pick_next(techs, cfg, False, -50) == SAT_ID
    assert pick_next(techs, {**cfg, "BuildSolarSatellites": False}, False, -50) is None
    techs[SHIPYARD] = Tech(SHIPYARD, 0, "on")
    techs[ROBOTS] = Tech(ROBOTS, 2, "on")
    assert pick_next(techs, cfg, False, -50) == SHIPYARD
    print("automine_pick ok")
