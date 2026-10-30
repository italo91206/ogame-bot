"""E05 AutoMine: worker + reexport I/O (`automine_io`)."""
from __future__ import annotations

import random
from typing import Any

from features.automine_io import (
    have_resources,
    mine_celestial,
    pad_moon_deut,
)
from features.automine_pick import (
    SAT_ID,
    SHIPYARD,
    excluded,
    pick_next,
)
from game import (
    Tech,
    parse_celestials,
    secs_until_resources,
)
from runtime import Worker, pick_schedule, schedule_why

# compat aliases (tests / callers)
_pad_moon_deut = pad_moon_deut
_have_resources = have_resources


class AutoMineWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        brain = settings.get("Brain") or {}
        cfg = brain.get("AutoMine") or {}
        if not brain.get("Active") or not cfg.get("Active"):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        exclude = cfg.get("Exclude") or []
        celestials = parse_celestials(page)
        if cfg.get("RandomOrder"):
            celestials = list(celestials)
            random.shuffle(celestials)

        tui = ctx.get("tui")
        refresh = ctx.get("refresh")
        lo_m, hi_m = self.interval_min / 60, self.interval_max / 60

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        built: list[str] = []
        waits: list[tuple[float, str]] = []
        todo = [c for c in celestials if not excluded(c, exclude)]
        if not celestials:
            wait_s, why = pick_schedule([], self.interval_min, self.interval_max)
            self._next_wait = wait_s
            self.reason = why
            _log(f"automine: {why} — retry {wait_s:.0f}s", "warn")
            return "retry DOM"
        if not todo:
            wait_s = random.uniform(self.interval_min, self.interval_max)
            self._next_wait = wait_s
            self.reason = f"todos excluded (CheckInterval {lo_m:.0f}–{hi_m:.0f}min)"
            _log(f"automine: próxima decisão em {wait_s:.0f}s — {self.reason}")
            return "excluded"

        leave_slots = int(ctx.get("slots_to_leave_free") or 1)
        for c in todo:
            tag = c.label
            try:
                result, wait, why, line = mine_celestial(
                    page,
                    c,
                    cfg,
                    self.interval_max,
                    book=ctx.get("resources"),
                    brain=brain,
                    leave_slots=leave_slots,
                )
            except Exception as e:
                err = str(e).split("\n", 1)[0][:100]
                built.append(f"{tag} err")
                _log(f"automine {tag}: erro UI ({err}) — retry 90s", "warn")
                waits.append((90.0, f"{tag}: erro UI"))
                continue
            lvl = "ok" if result and "→" in (result or "") else "info"
            if result and str(result).startswith("fail"):
                lvl = "warn"
            if result and str(result).startswith("Sat"):
                lvl = "ok"
            _log(f"automine {tag}: {line}", lvl)
            if (sw := schedule_why(wait, why, self.interval_min, self.interval_max)):
                waits.append((sw[0], f"{tag}: {sw[1]}"))
            if result and not str(result).startswith("wait"):
                built.append(f"{tag} {result}")
            elif result == "busy":
                built.append(f"{tag} busy")
            elif result and str(result).startswith("wait"):
                built.append(f"{tag} {result}")

        wait_s, why = pick_schedule(waits, self.interval_min, self.interval_max)
        self._next_wait = wait_s
        self.reason = why
        _log(f"automine: próxima decisão em {wait_s:.0f}s — {why}")
        return f"{len(built)} actions" if built else "nada"


if __name__ == "__main__":
    from features.automine_pick import (
        CRYSTAL,
        DEUT,
        LUNAR_BASE,
        JUMPGATE,
        METAL,
        SOLAR,
        pick_why as _pick_why,
    )

    techs = {
        METAL: Tech(METAL, 8, "on"),
        CRYSTAL: Tech(CRYSTAL, 6, "on"),
        DEUT: Tech(DEUT, 4, "disabled"),
        SOLAR: Tech(SOLAR, 10, "on"),
    }
    cfg = {
        "OptimizeForStart": True,
        "MaxMetalMine": 40,
        "MaxCrystalMine": 35,
        "MaxDeuteriumSynthetizer": 37,
        "MaxSolarPlant": 20,
        "MaxFusionReactor": 0,
        "MaxMetalStorage": 0,
        "MaxCrystalStorage": 0,
        "MaxDeuteriumTank": 0,
        "MaxRoboticsFactory": 0,
        "MaxShipyard": 0,
        "MaxResearchLab": 0,
        "MaxMissileSilo": 0,
        "MaxNaniteFactory": 0,
        "MaxTerraformer": 0,
        "MaxSpaceDock": 0,
        "BuildSolarSatellites": True,
    }
    assert pick_next(techs, cfg, False, 100) == METAL
    techs[METAL] = Tech(METAL, 12, "on")
    techs[CRYSTAL] = Tech(CRYSTAL, 10, "on")
    techs[DEUT] = Tech(DEUT, 8, "on")
    assert pick_next(techs, cfg, False, -10) == SOLAR
    techs[SOLAR] = Tech(SOLAR, 20, "on")
    assert pick_next(techs, cfg, False, -10) is None  # hangar 0 e cap 0
    techs[SHIPYARD] = Tech(SHIPYARD, 1, "on")
    cfg["MaxShipyard"] = 12
    assert pick_next(techs, cfg, False, -10) == SAT_ID
    assert pick_next(techs, cfg, False, 100) in (METAL, CRYSTAL, DEUT)
    moon = {LUNAR_BASE: Tech(LUNAR_BASE, 1, "on"), JUMPGATE: Tech(JUMPGATE, 0, "on")}
    assert pick_next(moon, {"MaxLunarBase": 8, "MaxJumpGate": 1}, True, 0) == LUNAR_BASE
    assert pad_moon_deut({"metal": 1, "crystal": 2, "deut": 3}, {}, False)["deut"] == 3
    assert pad_moon_deut(
        {"metal": 1, "crystal": 2, "deut": 3}, {"DeutToLeaveOnMoons": 100}, True
    )["deut"] == 103
    assert have_resources(
        {"metal": 10, "crystal": 10, "deut": 50},
        pad_moon_deut({"metal": 1, "crystal": 1, "deut": 1}, {"DeutToLeaveOnMoons": 40}, True),
    )
    assert not have_resources(
        {"metal": 10, "crystal": 10, "deut": 30},
        pad_moon_deut({"metal": 1, "crystal": 1, "deut": 1}, {"DeutToLeaveOnMoons": 40}, True),
    )

    assert secs_until_resources(
        {"metal": 1000, "crystal": 0, "deut": 0},
        {"metal": 0, "crystal": 0, "deut": 0},
        {"metal": 3600, "crystal": 0, "deut": 0},
    ) == 1000
    assert secs_until_resources(
        {"metal": 100, "crystal": 0, "deut": 0},
        {"metal": 50, "crystal": 0, "deut": 0},
        {"metal": 0, "crystal": 0, "deut": 0},
    ) is None
    poor = {
        METAL: Tech(METAL, 8, "disabled"),
        CRYSTAL: Tech(CRYSTAL, 6, "disabled"),
        DEUT: Tech(DEUT, 4, "off"),
        SOLAR: Tech(SOLAR, 10, "on"),
    }
    assert pick_next(poor, cfg, False, 100) is None
    assert pick_next(poor, cfg, False, 100, afford=False) == METAL
    early = {
        METAL: Tech(METAL, 8, "on"),
        CRYSTAL: Tech(CRYSTAL, 6, "on"),
        DEUT: Tech(DEUT, 4, "on"),
    }
    assert "OptimizeForStart" in _pick_why(METAL, early, cfg, False, 100)
    print("automine ok")
