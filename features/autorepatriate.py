"""E10 AutoRepatriate: haul resources from celestials → Target."""
from __future__ import annotations

import math
import random
from typing import Any

from game import (
    Celestial,
    current_resources,
    open_component,
    parse_celestials,
    parse_ogame_int,
    parse_slots,
    switch_celestial,
)
from game.fleet import (
    DEST_MOON,
    DEST_PLANET,
    MISSION_TRANSPORT,
    NAME_TO_ID,
    has_incoming_transport,
    parse_ships,
    send_fleet,
)
from runtime import Worker, slots_available


def _match_coords(c: Celestial, g: int, s: int, p: int, typ: str) -> bool:
    return (
        c.coords.galaxy == g
        and c.coords.system == s
        and c.coords.position == p
        and c.coords.type == typ
    )


def _excluded(c: Celestial, exclude: list) -> bool:
    for e in exclude or []:
        if _match_coords(
            c,
            int(e.get("Galaxy", -1)),
            int(e.get("System", -1)),
            int(e.get("Position", -1)),
            str(e.get("Type") or "Planet"),
        ):
            return True
    return False


def leave_deut_payload(
    metal: int,
    crystal: int,
    deut: int,
    *,
    leave: int,
    only_moons: bool,
    is_moon: bool,
) -> tuple[int, int, int]:
    if leave <= 0:
        return metal, crystal, deut
    if only_moons and not is_moon:
        return metal, crystal, deut
    return metal, crystal, max(0, deut - leave)


def clamp_payload(
    metal: int, crystal: int, deut: int, capacity: int
) -> tuple[int, int, int]:
    """Fill M→C→D up to cargo capacity."""
    cap = max(0, int(capacity))
    m = min(max(0, metal), cap)
    rem = cap - m
    c = min(max(0, crystal), rem)
    rem -= c
    d = min(max(0, deut), rem)
    return m, c, d


def ships_for_payload(
    total: int, cargo_per: int, have: int
) -> int:
    if total <= 0 or cargo_per <= 0 or have <= 0:
        return 0
    return min(have, int(math.ceil(total / float(cargo_per))))


class AutoRepatriateWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        brain = settings.get("Brain") or {}
        cfg = brain.get("AutoRepatriate") or {}
        if not (brain.get("Active") and cfg.get("Active")):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        leave_slots = int(ctx.get("slots_to_leave_free") or 1)
        tui = ctx.get("tui")
        refresh = ctx.get("refresh")
        runtime = ctx.get("runtime")

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        target = cfg.get("Target") or {}
        try:
            tg = int(target["Galaxy"])
            ts = int(target["System"])
            tp = int(target["Position"])
        except (KeyError, TypeError, ValueError):
            self.reason = "configure Target"
            _log("repatriate: falta Target em settings.json", "error")
            return "sem Target"
        if tg <= 0 or ts <= 0 or tp <= 0:
            self.reason = "configure Target"
            _log("repatriate: falta Target em settings.json", "error")
            return "sem Target"
        ttype = str(target.get("Type") or "Planet")
        dest_type = DEST_MOON if ttype == "Moon" else DEST_PLANET

        cargo_name = str(cfg.get("CargoType") or "LargeCargo")
        sid = NAME_TO_ID.get(cargo_name) or NAME_TO_ID["LargeCargo"]
        min_res = int(cfg.get("MinimumResources") or 0)
        exclude_moons = bool(cfg.get("ExcludeMoons"))
        skip_in = bool(cfg.get("SkipIfIncomingTransport", True))
        random_order = bool(cfg.get("RandomOrder"))
        leave_cfg = cfg.get("LeaveDeut") or {}
        deut_leave = int(leave_cfg.get("DeutToLeave") or 0)
        only_moons = bool(leave_cfg.get("OnlyOnMoons", True))
        exclude = cfg.get("Exclude") or []

        celestials = parse_celestials(page)
        if not celestials:
            self._next_wait = random.uniform(30, 90)
            self.reason = "planetList vazio"
            return "sem planetas"

        sources = [
            c
            for c in celestials
            if not _match_coords(c, tg, ts, tp, ttype)
            and not _excluded(c, exclude)
            and not (exclude_moons and c.coords.type == "Moon")
        ]
        if random_order:
            random.shuffle(sources)
        else:
            sources.sort(
                key=lambda c: (
                    abs(c.coords.galaxy - tg) * 20000
                    + abs(c.coords.system - ts) * 95
                    + abs(c.coords.position - tp)
                )
            )

        sent = 0
        for c in sources:
            if runtime and not runtime.can_send_fleet(page):
                self.reason = f"slots · enviou {sent}"
                _log(f"repatriate: sem slot (enviou {sent})", "warn")
                return f"slots · {sent} envios" if sent else "sem slot"

            switch_celestial(page, c)
            if skip_in and has_incoming_transport(
                page,
                c.coords.galaxy,
                c.coords.system,
                c.coords.position,
                moon=c.coords.type == "Moon",
            ):
                continue

            res = current_resources(page)
            metal = parse_ogame_int(res.get("metal", "0"))
            crystal = parse_ogame_int(res.get("crystal", "0"))
            deut = parse_ogame_int(res.get("deut", "0"))
            metal, crystal, deut = leave_deut_payload(
                metal,
                crystal,
                deut,
                leave=deut_leave,
                only_moons=only_moons,
                is_moon=c.coords.type == "Moon",
            )
            total = metal + crystal + deut
            if total < min_res or total <= 0:
                continue

            open_component(page, "fleetdispatch")
            if not slots_available(parse_slots(page), leave_slots):
                self.reason = f"slots · enviou {sent}"
                return f"slots · {sent} envios" if sent else "sem slot"

            ships = parse_ships(page)
            have = ships.get(sid, {}).get("number", 0)
            cargo_per = ships.get(sid, {}).get("cargo", 0) or (
                25000 if sid == 203 else 5000
            )
            n = ships_for_payload(total, cargo_per, have)
            if n <= 0:
                continue
            m, cr, d = clamp_payload(metal, crystal, deut, n * cargo_per)
            if m + cr + d <= 0:
                continue

            status = send_fleet(
                page,
                {sid: n},
                tg,
                ts,
                tp,
                mission=MISSION_TRANSPORT,
                dest_type=dest_type,
                metal=m,
                crystal=cr,
                deut=d,
            )
            if status == "ok":
                sent += 1
                _log(
                    f"repatriate: {c.label} → [{tg}:{ts}:{tp}] "
                    f"{n}x{cargo_name} M{m}+C{cr}+D{d}",
                    "ok",
                )
            else:
                _log(f"repatriate {c.label}: {status}", "warn")
                self.reason = status
                return status if not sent else f"{sent} ok · {status}"

        self.reason = f"enviou {sent}" if sent else "nada a recolher"
        return self.reason


if __name__ == "__main__":
    assert leave_deut_payload(100, 100, 500, leave=200, only_moons=True, is_moon=True) == (
        100,
        100,
        300,
    )
    assert leave_deut_payload(100, 100, 500, leave=200, only_moons=True, is_moon=False) == (
        100,
        100,
        500,
    )
    assert clamp_payload(1000, 1000, 1000, 1500) == (1000, 500, 0)
    assert ships_for_payload(100_000, 25_000, 10) == 4
    assert ships_for_payload(100_000, 25_000, 2) == 2
    assert ships_for_payload(0, 25_000, 10) == 0
    print("autorepatriate ok")
