"""Wire settings → Runtime workers (keeps main.py under 500 LOC)."""
from __future__ import annotations

from features.autocargo import AutoCargoWorker
from features.autocolonize import AutoColonizeWorker
from features.autodiscovery import AutoDiscoveryWorker
from features.autofarm import AutoFarmWorker
from features.autoharvest import AutoHarvestWorker
from features.automine import AutoMineWorker
from features.autorepatriate import AutoRepatriateWorker
from features.autoresearch import AutoResearchWorker
from features.defender import DefenderWorker
from features.expeditions import ExpeditionsWorker
from features.lifeform_automine import LifeformAutoMineWorker
from features.lifeform_autoresearch import LifeformAutoResearchWorker
from features.overview import OverviewWorker
from features.sleepmode import SleepModeWorker
from runtime import Runtime


def _brain_iv(brain: dict, key: str, dmin: float, dmax: float) -> tuple[bool, float, float]:
    cfg = brain.get(key) or {}
    on = bool(brain.get("Active")) and bool(cfg.get("Active"))
    lo = float(cfg.get("CheckIntervalMin") or dmin) * 60
    hi = float(cfg.get("CheckIntervalMax") or dmax) * 60
    return on, lo, max(lo, hi)


def build_runtime(settings: dict) -> Runtime:
    general = settings.get("General") or {}
    leave = int(general.get("SlotsToLeaveFree") or 1)
    isolate = bool(general.get("IsolateExpeditions"))
    brain = settings.get("Brain") or {}

    am_on, am_lo, am_hi = _brain_iv(brain, "AutoMine", 10, 20)
    ar_on, ar_lo, ar_hi = _brain_iv(brain, "AutoResearch", 10, 20)
    lam_on, lam_lo, lam_hi = _brain_iv(brain, "LifeformAutoMine", 30, 60)
    lar_on, lar_lo, lar_hi = _brain_iv(brain, "LifeformAutoResearch", 30, 60)
    cargo_on, cargo_lo, cargo_hi = _brain_iv(brain, "AutoCargo", 60, 120)
    rpat_on, rpat_lo, rpat_hi = _brain_iv(brain, "AutoRepatriate", 30, 60)

    expo = settings.get("Expeditions") or {}
    expo_lo = float(expo.get("MinWaitNextFleet") or 5)
    expo_hi = max(expo_lo, float(expo.get("MaxWaitNextRound") or 300))

    farm = settings.get("AutoFarm") or {}
    farm_lo = float(farm.get("CheckIntervalMin") or 30) * 60
    farm_hi = max(farm_lo, float(farm.get("CheckIntervalMax") or 60) * 60)

    harv = settings.get("AutoHarvest") or {}
    harv_lo = float(harv.get("CheckIntervalMin") or 30) * 60
    harv_hi = max(harv_lo, float(harv.get("CheckIntervalMax") or 60) * 60)

    colo = settings.get("AutoColonize") or {}
    colo_lo = float(colo.get("CheckIntervalMin") or 30) * 60
    colo_hi = max(colo_lo, float(colo.get("CheckIntervalMax") or 60) * 60)

    disc = settings.get("AutoDiscovery") or {}
    disc_lo = float(disc.get("CheckIntervalMin") or 30) * 60
    disc_hi = max(disc_lo, float(disc.get("CheckIntervalMax") or 60) * 60)

    # Defender CheckInterval = seconds (TBot)
    defn = settings.get("Defender") or {}
    def_lo = max(1.0, float(defn.get("CheckIntervalMin") or 1))
    def_hi = max(def_lo, float(defn.get("CheckIntervalMax") or 22))

    return Runtime(
        [
            SleepModeWorker("SleepMode", active=not isolate, interval_min=60, interval_max=120),
            DefenderWorker(
                "Defender",
                active=bool(defn.get("Active", True)),
                interval_min=def_lo,
                interval_max=def_hi,
            ),
            OverviewWorker("Overview", active=not isolate, interval_min=45, interval_max=75),
            ExpeditionsWorker(
                "Expeditions",
                active=bool(expo.get("Active")),
                interval_min=expo_lo,
                interval_max=expo_hi,
            ),
            AutoFarmWorker(
                "AutoFarm",
                active=bool(farm.get("Active", True)),
                interval_min=farm_lo,
                interval_max=farm_hi,
            ),
            AutoHarvestWorker(
                "AutoHarvest",
                active=bool(harv.get("Active")),
                interval_min=harv_lo,
                interval_max=harv_hi,
            ),
            AutoColonizeWorker(
                "AutoColonize",
                active=bool(colo.get("Active")),
                interval_min=colo_lo,
                interval_max=colo_hi,
            ),
            AutoDiscoveryWorker(
                "AutoDiscovery",
                active=bool(disc.get("Active")),
                interval_min=disc_lo,
                interval_max=disc_hi,
            ),
            AutoMineWorker("AutoMine", active=am_on, interval_min=am_lo, interval_max=am_hi),
            AutoResearchWorker(
                "AutoResearch", active=ar_on, interval_min=ar_lo, interval_max=ar_hi
            ),
            LifeformAutoMineWorker(
                "LifeformAutoMine", active=lam_on, interval_min=lam_lo, interval_max=lam_hi
            ),
            LifeformAutoResearchWorker(
                "LifeformAutoResearch",
                active=lar_on,
                interval_min=lar_lo,
                interval_max=lar_hi,
            ),
            AutoCargoWorker(
                "AutoCargo", active=cargo_on, interval_min=cargo_lo, interval_max=cargo_hi
            ),
            AutoRepatriateWorker(
                "AutoRepatriate", active=rpat_on, interval_min=rpat_lo, interval_max=rpat_hi
            ),
        ],
        slots_to_leave_free=leave,
    )
