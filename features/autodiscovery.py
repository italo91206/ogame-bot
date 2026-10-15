"""E15 AutoDiscovery: missões Discovery (18) a partir do Origin."""
from __future__ import annotations

import random
import time
from typing import Any

from game import (
    Celestial,
    Coords,
    current_resources,
    fleet_slots,
    ogame_distance,
    open_component,
    parse_celestials,
    parse_ogame_int,
    send_discovery,
    switch_celestial,
)
from game.fleet import MISSION_DISCOVERY
from runtime import Worker, slots_available

# TBot: Metal 5000 / Crystal 1000 / Deuterium 500
COST_METAL, COST_CRYSTAL, COST_DEUT = 5000, 1000, 500
DAY_S = 86400.0
# ponytail: 499 sistemas (universo típico); subir se serverData.Systems > 499
N_SYSTEMS = 499


def _match_origin(c: Celestial, origin: dict) -> bool:
    return (
        c.coords.galaxy == int(origin.get("Galaxy", -1))
        and c.coords.system == int(origin.get("System", -1))
        and c.coords.position == int(origin.get("Position", -1))
        and c.coords.type == (origin.get("Type") or "Planet")
    )


def discovery_fleets_out(page) -> int:
    return page.locator(f'tr.eventFleet[data-mission-type="{MISSION_DISCOVERY}"]').count()


def can_afford(page) -> bool:
    r = current_resources(page)
    return (
        parse_ogame_int(r.get("metal", "0")) >= COST_METAL
        and parse_ogame_int(r.get("crystal", "0")) >= COST_CRYSTAL
        and parse_ogame_int(r.get("deut", "0")) >= COST_DEUT
    )


def destinations(origin: Coords, n_systems: int = N_SYSTEMS) -> list[Coords]:
    """Shuffle then nearest-first (TBot)."""
    g = origin.galaxy
    dests = [
        Coords(g, s, p, "Planet")
        for s in range(1, int(n_systems) + 1)
        for p in range(1, 16)
    ]
    random.shuffle(dests)
    dests.sort(key=lambda c: ogame_distance(origin, c))
    return dests


class AutoDiscoveryWorker(Worker):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # (g,s,p) → unix expiry
        self._blacklist: dict[tuple[int, int, int], float] = {}

    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        cfg = settings.get("AutoDiscovery") or {}
        if not cfg.get("Active"):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        leave = int(ctx.get("slots_to_leave_free") or 1)
        max_slots = int(cfg.get("MaxSlots") or 5)
        max_fail = int(cfg.get("MaxFailures") or 5)
        wait = random.uniform(self.interval_min, self.interval_max)
        tui = ctx.get("tui")
        refresh = ctx.get("refresh")

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        # SleepMode: Runtime já bloqueia workers quando sleeping

        celestials = parse_celestials(page)
        if not celestials:
            self._next_wait = random.uniform(30, 90)
            self.reason = "planetList vazio"
            return "retry DOM"

        origin_cfg = cfg.get("Origin") or {}
        origin = next((c for c in celestials if _match_origin(c, origin_cfg)), None)
        if origin is None:
            self._next_wait = wait
            self.reason = "sem Origin"
            _log("discovery: sem Origin", "warn")
            return self.reason

        now = time.time()
        # purge expired
        self._blacklist = {k: exp for k, exp in self._blacklist.items() if exp > now}

        out = discovery_fleets_out(page)
        if out >= max_slots:
            self._next_wait = wait
            self.reason = f"slots discovery {out}/{max_slots}"
            return self.reason

        switch_celestial(page, origin)
        open_component(page, "fleetdispatch")
        slots = fleet_slots(page)
        if slots.total <= 0 or not slots_available(slots, leave):
            self._next_wait = wait
            self.reason = "sem slot frota"
            return self.reason
        if not can_afford(page):
            self._next_wait = wait
            self.reason = "sem res (5k/1k/500)"
            _log("discovery: recursos insuficientes", "warn")
            return self.reason

        sent = 0
        fails = 0
        for dest in destinations(origin.coords):
            if out + sent >= max_slots:
                break
            if fails >= max_fail:
                break
            if not slots_available(fleet_slots(page), leave):
                break
            key = (dest.galaxy, dest.system, dest.position)
            if key in self._blacklist:
                continue
            if not can_afford(page):
                break

            status = send_discovery(page, dest.galaxy, dest.system, dest.position)
            tag = f"{dest.galaxy}:{dest.system}:{dest.position}"
            if status == "ok":
                sent += 1
                self._blacklist[key] = now + 7 * DAY_S
                _log(f"discovery: ok → {tag}", "ok")
            else:
                fails += 1
                self._blacklist[key] = now + DAY_S
                _log(f"discovery: fail {status} → {tag}", "warn")

        self._next_wait = wait
        if sent:
            self.reason = f"{sent} sent · fail {fails}"
        elif fails:
            self.reason = f"fail {fails}"
        else:
            self.reason = "nada (blacklist/slots)"
        return self.reason


if __name__ == "__main__":
    o = Coords(1, 10, 8, "Planet")
    d = destinations(o, n_systems=2)
    assert len(d) == 2 * 15
    assert d[0].galaxy == 1
    # nearest to origin should be same system first-ish after shuffle+sort
    assert all(c.system <= 2 for c in d)
    assert ogame_distance(o, d[0]) <= ogame_distance(o, d[-1])
    print("autodiscovery ok")
