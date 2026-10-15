"""E03 Expeditions: fill expo slots; pacing + fuel (T01–T04, T06)."""
from __future__ import annotations

import math
import random
from typing import Any

from game import (
    Celestial,
    FleetSlots,
    open_component,
    parse_celestials,
    parse_slots,
    switch_celestial,
)
from game.fleet import (
    NAME_TO_ID,
    expo_back_in,
    freight_cap,
    is_discoverer,
    parse_ships,
    pick_extras,
    send_expedition,
    universe_speed,
)
from runtime import Worker


def _origin_match(c: Celestial, origins: list) -> bool:
    if not origins:
        return True
    for o in origins:
        if (
            int(o.get("Galaxy", -1)) == c.coords.galaxy
            and int(o.get("System", -1)) == c.coords.system
            and int(o.get("Position", -1)) == c.coords.position
            and (o.get("Type") or "Planet") == c.coords.type
        ):
            return True
    return False


def exps_to_send(slots: FleetSlots, leave: int, cfg: dict) -> int:
    """TBot WaitForAll / WaitForMajority → how many expos this tick may fill."""
    fleet_room = max(0, slots.free - leave)
    if cfg.get("WaitForAllExpeditions"):
        in_use = max(0, slots.exp_total - slots.exp_free)
        if in_use > 0:
            return 0
        return min(slots.exp_total, fleet_room)
    n = min(slots.exp_free, fleet_room)
    if cfg.get("WaitForMajorityOfExpeditions"):
        # need at least floor(total/2)+1 free before starting a new wave
        if n < (slots.exp_total // 2) + 1:
            return 0
    return n


def _round_wait(page, cfg: dict) -> float:
    lo = float(cfg.get("MinWaitNextRound") or 30)
    hi = float(cfg.get("MaxWaitNextRound") or 300)
    pad = random.uniform(lo, hi)
    back = expo_back_in(page, latest=bool(cfg.get("WaitForAllExpeditions")))
    return (back + pad) if back is not None else random.uniform(lo, hi)


def ideal_primary_count(cap: int, cargo_per: int) -> int:
    if cargo_per <= 0 or cap <= 0:
        return 0
    return int(math.ceil(cap / float(cargo_per)))


def build_expo_ships(
    available: dict[int, dict[str, int]],
    *,
    primary: str,
    min_primary: int,
    primary_to_keep: int,
    secondary: str,
    min_secondary: int,
    secondary_ratio: float,
    expos_from_origin: int,
    top_score: float,
    discoverer: bool,
    eco_speed: int,
) -> dict[int, int] | None:
    """TBot CalcFullExpeditionShips (sans LF bonus). None if cannot send."""
    if expos_from_origin <= 0:
        return None
    pid = NAME_TO_ID.get(primary) or NAME_TO_ID["LargeCargo"]
    stock = dict(available)
    have = stock.get(pid, {}).get("number", 0)
    usable = max(0, have - max(0, primary_to_keep))
    cargo = stock.get(pid, {}).get("cargo", 0) or (25000 if pid == 203 else 5000)
    cap = freight_cap(top_score, discoverer=discoverer, eco_speed=eco_speed)
    ideal = ideal_primary_count(cap, cargo)
    per = min(usable // expos_from_origin, ideal) if expos_from_origin else 0
    if per < min_primary:
        per = min_primary
    if usable < per * expos_from_origin:
        return None
    fleet: dict[int, int] = {pid: per}

    sid_name = (secondary or "Null").strip()
    if sid_name and sid_name.lower() != "null":
        sid = NAME_TO_ID.get(sid_name)
        if sid:
            savail = stock.get(sid, {}).get("number", 0)
            sec = min(
                int(savail // expos_from_origin),
                int(per * float(secondary_ratio)),
            )
            if sec < min_secondary:
                return None
            if sec > 0:
                fleet[sid] = sec
                if savail < sec * expos_from_origin:
                    return None

    for eid, n in pick_extras(stock, expos_from_origin).items():
        fleet[eid] = fleet.get(eid, 0) + n
        need = fleet[eid] * expos_from_origin
        if stock.get(eid, {}).get("number", 0) < need:
            fleet.pop(eid, None)
    return fleet


def _fleet_label(ships: dict[int, int]) -> str:
    from game.fleet import SHIP_NAMES

    parts = [f"{n} {SHIP_NAMES.get(i, i)}" for i, n in sorted(ships.items()) if n]
    return ", ".join(parts) or "—"


class ExpeditionsWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        cfg = settings.get("Expeditions") or {}
        if not cfg.get("Active"):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        # General = floor (jogador); Expo pode deixar mais p/ Colonize/Brain
        leave = max(
            int(ctx.get("slots_to_leave_free") or 1),
            int(cfg.get("SlotsToLeaveFree") or 0),
        )
        tui = ctx.get("tui")
        refresh = ctx.get("refresh")

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        open_component(page, "fleetdispatch")
        slots = parse_slots(page)
        if slots.total <= 0:
            self._next_wait = random.uniform(20, 45)
            self.reason = "slots DOM 0/0"
            _log("expo: parse slots falhou (0/0) — retry", "warn")
            return "slots DOM"
        to_send = exps_to_send(slots, leave, cfg)
        if to_send <= 0:
            wait = _round_wait(page, cfg)
            self._next_wait = wait
            self.reason = (
                f"pacing fleet={slots.free}/{slots.total} "
                f"expo={slots.exp_free}/{slots.exp_total}"
            )
            _log(f"expo: {self.reason} — next {wait:.0f}s")
            return "aguardando slot"

        origins_cfg = cfg.get("Origin") or []
        celestials = parse_celestials(page)
        origins = [c for c in celestials if _origin_match(c, origins_cfg)]
        if not origins:
            # sem Origin: só planetas (lua raramente é base de expo)
            origins = [c for c in celestials if c.coords.type == "Planet"]
            if not origins:
                origins = list(celestials)
        if not origins:
            self._next_wait = random.uniform(30, 90)
            self.reason = "sem origin"
            return "sem origin"

        primary = str(cfg.get("PrimaryShip") or "LargeCargo")
        min_pri = int(cfg.get("MinPrimaryToSend") or 1)
        keep = int(cfg.get("PrimaryToKeep") or 0)
        secondary = str(cfg.get("SecondaryShip") or "Null")
        min_sec = int(cfg.get("MinSecondaryToSend") or 0)
        ratio = float(cfg.get("SecondaryToPrimaryRatio") or 0)
        top = float(cfg.get("TopScore") or 50_000_000)
        fuel = max(0, int(cfg.get("FuelToCarry") or 0))
        eco = universe_speed(page)
        disc = is_discoverer(page)

        # 1 expo / tick (ponytail: avoids blocking sleep between fleets)
        quot = max(1, to_send // len(origins))
        if cfg.get("RandomizeOrder", True):
            random.shuffle(origins)
        for origin in origins:
            switch_celestial(page, origin)
            open_component(page, "fleetdispatch")
            ships_here = parse_ships(page)
            fleet = build_expo_ships(
                ships_here,
                primary=primary,
                min_primary=min_pri,
                primary_to_keep=keep,
                secondary=secondary,
                min_secondary=min_sec,
                secondary_ratio=ratio,
                expos_from_origin=quot,
                top_score=top,
                discoverer=disc,
                eco_speed=eco,
            )
            if not fleet:
                # try single expo from this origin
                fleet = build_expo_ships(
                    ships_here,
                    primary=primary,
                    min_primary=min_pri,
                    primary_to_keep=keep,
                    secondary=secondary,
                    min_secondary=min_sec,
                    secondary_ratio=ratio,
                    expos_from_origin=1,
                    top_score=top,
                    discoverer=disc,
                    eco_speed=eco,
                )
            if not fleet:
                have = ships_here.get(
                    NAME_TO_ID.get(primary) or 203, {}
                ).get("number", 0)
                _log(
                    f"expo {origin.label}: skip (primary {primary}={have} "
                    f"quot={quot} ships={sum(s.get('number',0) for s in ships_here.values())})",
                    "warn",
                )
                continue
            g, s = origin.coords.galaxy, origin.coords.system
            status = send_expedition(page, fleet, g, s, deut=fuel)
            label = _fleet_label(fleet)
            if status == "ok":
                lo = float(cfg.get("MinWaitNextFleet") or 5)
                hi = float(cfg.get("MaxWaitNextFleet") or 15)
                wait = random.uniform(lo, hi)
                self._next_wait = wait
                self.reason = f"enviou {_fleet_label(fleet)} de {origin.label}"
                _log(f"expo: enviou {label} {origin.label} → [{g}:{s}:16]", "ok")
                return f"enviou {label}"
            _log(f"expo {origin.label}: {status} ({label})", "warn")
            self.reason = status
            self._next_wait = random.uniform(30, 90)
            return status

        self._next_wait = random.uniform(60, 180)
        self.reason = "sem naves / min"
        _log("expo: sem naves suficientes nos origins", "warn")
        return "sem naves"


if __name__ == "__main__":
    assert ideal_primary_count(5_000_000, 25_000) == 200
    assert ideal_primary_count(100, 25000) == 1
    avail = {
        203: {"number": 5000, "cargo": 25000},
        210: {"number": 10, "cargo": 0},
        219: {"number": 5, "cargo": 10000},
        218: {"number": 3, "cargo": 10000},
    }
    f = build_expo_ships(
        avail,
        primary="LargeCargo",
        min_primary=1,
        primary_to_keep=0,
        secondary="Null",
        min_secondary=0,
        secondary_ratio=0,
        expos_from_origin=2,
        top_score=100_000_000,
        discoverer=False,
        eco_speed=1,
    )
    assert f and f[203] >= 1 and f.get(210) == 1 and f.get(218) == 1
    # PrimaryToKeep blocks
    assert (
        build_expo_ships(
            {203: {"number": 100, "cargo": 25000}},
            primary="LargeCargo",
            min_primary=50,
            primary_to_keep=100,
            secondary="Null",
            min_secondary=0,
            secondary_ratio=0,
            expos_from_origin=1,
            top_score=10_000,
            discoverer=False,
            eco_speed=1,
        )
        is None
    )
    s = FleetSlots(free=5, total=10, exp_free=2, exp_total=4)
    assert exps_to_send(s, 1, {}) == 2
    assert exps_to_send(s, 2, {}) == 2  # leave 2 → fleet_room 3, capped by exp_free 2
    assert exps_to_send(FleetSlots(free=2, total=14, exp_free=3, exp_total=9), 2, {}) == 0
    assert exps_to_send(s, 1, {"WaitForAllExpeditions": True}) == 0
    assert exps_to_send(
        FleetSlots(free=5, total=10, exp_free=4, exp_total=4),
        1,
        {"WaitForAllExpeditions": True},
    ) == 4
    assert exps_to_send(s, 1, {"WaitForMajorityOfExpeditions": True}) == 0
    assert exps_to_send(
        FleetSlots(free=5, total=10, exp_free=3, exp_total=4),
        1,
        {"WaitForMajorityOfExpeditions": True},
    ) == 3
    print("expeditions ok")
