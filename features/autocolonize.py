"""E14 AutoColonize: send colony ships into empty target slots (core T01+T04)."""
from __future__ import annotations

import random
from typing import Any

from features.autocargo import shipyard_producing, ships_in_shipyard_queue
from game import (
    Celestial,
    Coords,
    fleet_slots,
    open_component,
    parse_celestials,
    parse_technologies,
    switch_celestial,
)
from game.fleet import MISSION_COLONIZE, parse_ships, send_fleet
from game.galaxy import fetch_empty_system, ogame_distance
from game.tech import build_ships
from runtime import Worker, slots_available

ASTRO_ID = 124
CS_ID = 208


def max_planets(astro: int) -> int:
    """TBot CalcMaxPlanets: floor((astro + 3) / 2)."""
    return (int(astro) + 3) // 2


def astro_allows_pos(pos: int, astro: int) -> bool:
    """TBot CalcLimitAstro."""
    a = int(astro)
    p = int(pos)
    if a >= 8:
        return 1 <= p <= 15
    if a >= 6:
        return 2 <= p <= 14
    if a >= 4:
        return 4 <= p <= 13
    return False


def _match_origin(c: Celestial, origin: dict) -> bool:
    return (
        c.coords.galaxy == int(origin.get("Galaxy", -1))
        and c.coords.system == int(origin.get("System", -1))
        and c.coords.position == int(origin.get("Position", -1))
        and c.coords.type == (origin.get("Type") or "Planet")
    )


def planets_in_range(owned: list[Celestial], t: dict) -> int:
    g = int(t.get("Galaxy") or 0)
    s0, s1 = int(t.get("StartSystem") or 0), int(t.get("EndSystem") or 0)
    p0, p1 = int(t.get("StartPosition") or 1), int(t.get("EndPosition") or 15)
    if s1 < s0:
        s0, s1 = s1, s0
    if p1 < p0:
        p0, p1 = p1, p0
    n = 0
    for c in owned:
        if c.coords.type != "Planet":
            continue
        if c.coords.galaxy != g:
            continue
        if not (s0 <= c.coords.system <= s1):
            continue
        if p0 <= c.coords.position <= p1:
            n += 1
    return n


def colonize_fleets_out(page) -> int:
    rows = page.locator('tr.eventFleet[data-mission-type="7"]')
    n = 0
    for i in range(rows.count()):
        ret = rows.nth(i).get_attribute("data-return-flight") or ""
        if ret not in ("true", "1"):
            n += 1
    return n


def colonize_incoming(page, dest: Coords) -> bool:
    rows = page.locator('tr.eventFleet[data-mission-type="7"]')
    for i in range(rows.count()):
        el = rows.nth(i)
        ret = el.get_attribute("data-return-flight") or ""
        if ret in ("true", "1"):
            continue
        dest_txt = (
            el.locator("td.destCoords").inner_text()
            if el.locator("td.destCoords").count()
            else ""
        )
        # "1:77:6" or "[1:77:6]"
        parts = [p for p in dest_txt.replace("[", "").replace("]", "").split(":") if p.strip()]
        if len(parts) < 3:
            continue
        try:
            g, s, p = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if g == dest.galaxy and s == dest.system and p == dest.position:
            return True
    return False


def pick_empty_targets(
    page,
    targets: list,
    owned: list[Celestial],
    owned_keys: set[tuple[int, int, int]],
    astro: int,
    *,
    need: int,
    randomize: bool,
    origin: Coords,
) -> list[Coords]:
    """Scan Target ranges for empty slots; stop when `need` found."""
    found: list[Coords] = []
    for t in targets or []:
        if planets_in_range(owned, t) >= int(t.get("MaxPlanets") or 99):
            continue
        g = int(t.get("Galaxy") or 0)
        s0, s1 = int(t.get("StartSystem") or 0), int(t.get("EndSystem") or 0)
        p0, p1 = int(t.get("StartPosition") or 1), int(t.get("EndPosition") or 15)
        if g <= 0 or s0 <= 0 or s1 <= 0:
            continue
        if s1 < s0:
            s0, s1 = s1, s0
        if p1 < p0:
            p0, p1 = p1, p0
        systems = list(range(s0, s1 + 1))
        if randomize:
            random.shuffle(systems)
        for sys in systems:
            for c in fetch_empty_system(page, g, sys):
                if c.galaxy <= 0 or c.system <= 0:
                    continue
                if not (p0 <= c.position <= p1):
                    continue
                if not astro_allows_pos(c.position, astro):
                    continue
                if (c.galaxy, c.system, c.position) in owned_keys:
                    continue
                found.append(c)
            if len(found) >= need:
                break
        if len(found) >= need:
            break
    if randomize:
        random.shuffle(found)
    else:
        found.sort(key=lambda c: ogame_distance(origin, c))
    return found[:need]


class AutoColonizeWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        cfg = settings.get("AutoColonize") or {}
        if not cfg.get("Active"):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        leave_fleet = int(ctx.get("slots_to_leave_free") or 1)
        leave_planet = int(cfg.get("SlotsToLeaveFree") or 0)
        tui = ctx.get("tui")
        refresh = ctx.get("refresh")

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        wait = random.uniform(self.interval_min, self.interval_max)
        celestials = parse_celestials(page)
        if not celestials:
            self._next_wait = random.uniform(30, 90)
            self.reason = "planetList vazio"
            return "retry DOM"

        planets = [c for c in celestials if c.coords.type == "Planet"]
        open_component(page, "research")
        techs = parse_technologies(page)
        astro = int((techs.get(ASTRO_ID).level if ASTRO_ID in techs else 0) or 0)
        cap = max_planets(astro)
        need = cap - len(planets) - leave_planet
        if need <= 0:
            self._next_wait = wait
            self.reason = f"slots ok {len(planets)}/{cap}"
            return self.reason

        out = colonize_fleets_out(page)
        if out >= need:
            self._next_wait = wait
            self.reason = f"CS em voo ({out})"
            _log(f"colonize: {self.reason}")
            return self.reason

        origin_cfg = cfg.get("Origin") or {}
        origin = next((c for c in celestials if _match_origin(c, origin_cfg)), None)
        if origin is None:
            origin = next((c for c in planets), None)
        if origin is None:
            self._next_wait = wait
            self.reason = "sem Origin"
            return self.reason

        switch_celestial(page, origin)
        open_component(page, "fleetdispatch")
        slots = fleet_slots(page)
        if slots.total <= 0:
            self._next_wait = random.uniform(20, 45)
            self.reason = "slots DOM 0/0"
            return self.reason
        if not slots_available(slots, leave_fleet):
            self._next_wait = wait
            self.reason = f"sem slot frota ({slots.free}/{slots.total})"
            return self.reason
        ships = parse_ships(page)
        have_cs = int(ships.get(CS_ID, {}).get("number") or 0)
        still = need - out
        if have_cs < still:
            open_component(page, "shipyard")
            queued = ships_in_shipyard_queue(page, CS_ID)
            if have_cs + queued >= still:
                self._next_wait = wait
                self.reason = f"CS fila/hangar ({have_cs}+{queued}>={still})"
                _log(f"colonize: aguardando CS — {self.reason}")
                return self.reason
            if shipyard_producing(page):
                self._next_wait = wait
                self.reason = "estaleiro ocupado"
                _log("colonize: construindo CS — estaleiro ocupado")
                return self.reason
            want = still - have_cs - queued
            fail = build_ships(page, CS_ID, want)
            if fail:
                self._next_wait = wait
                self.reason = f"build CS falhou ({fail})"
                _log(f"colonize: {self.reason}", "warn")
                return self.reason
            self._next_wait = wait
            self.reason = f"build {want}xCS"
            _log(f"colonize: build {want}x ColonyShip", "ok")
            return self.reason

        owned_keys = {
            (c.coords.galaxy, c.coords.system, c.coords.position)
            for c in planets
        }
        # 1 CS / tick
        cands = pick_empty_targets(
            page,
            cfg.get("Targets") or [],
            planets,
            owned_keys,
            astro,
            need=1,
            randomize=bool(cfg.get("RandomPosition", True)),
            origin=origin.coords,
        )
        if not cands:
            self._next_wait = wait
            self.reason = "sem slot vazio nos Targets"
            _log(f"colonize: {self.reason}", "warn")
            return self.reason

        dest = cands[0]
        if dest.galaxy <= 0 or dest.system <= 0:
            self._next_wait = wait
            self.reason = f"coords inválidas {dest}"
            _log(f"colonize: {self.reason}", "warn")
            return self.reason
        if colonize_incoming(page, dest):
            self._next_wait = wait
            self.reason = f"já incoming {dest}"
            return self.reason

        switch_celestial(page, origin)
        open_component(page, "fleetdispatch")
        status = send_fleet(
            page,
            {CS_ID: 1},
            dest.galaxy,
            dest.system,
            dest.position,
            mission=MISSION_COLONIZE,
        )
        tag = f"{dest.galaxy}:{dest.system}:{dest.position}"
        if status == "ok":
            self._next_wait = wait
            self.reason = f"ok → {tag}"
            _log(f"colonize: enviado CS → {tag}", "ok")
            return self.reason

        self._next_wait = wait
        self.reason = f"fail {status}"
        _log(f"colonize: fail {status} → {tag}", "warn")
        return self.reason


if __name__ == "__main__":
    assert max_planets(0) == 1
    assert max_planets(1) == 2
    assert max_planets(4) == 3
    assert max_planets(7) == 5
    assert max_planets(8) == 5
    assert astro_allows_pos(8, 4) and not astro_allows_pos(1, 4)
    assert astro_allows_pos(1, 8) and astro_allows_pos(15, 8)
    assert planets_in_range(
        [
            Celestial("a", "1", Coords(1, 10, 8, "Planet")),
            Celestial("b", "2", Coords(1, 20, 8, "Planet")),
        ],
        {
            "Galaxy": 1,
            "StartSystem": 1,
            "EndSystem": 15,
            "StartPosition": 4,
            "EndPosition": 13,
            "MaxPlanets": 2,
        },
    ) == 1
    print("autocolonize ok")
