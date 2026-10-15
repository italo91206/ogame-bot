"""E13 AutoHarvest: reciclar DF próprio e deep space (expo) acima de thresholds."""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any

from game import (
    Celestial,
    Coords,
    fleet_slots,
    open_component,
    parse_celestials,
    parse_ships,
    send_fleet,
    switch_celestial,
)
from game.fleet import DEST_DEBRIS, MISSION_HARVEST
from game.galaxy import DebrisField, clamp_system, fetch_debris_near
from runtime import Worker, slots_available

SHIP_RECY = 209
SHIP_PF = 219
# fallback se shipsOnPlanet não trouxer cargo
_DEFAULT_CARGO = {SHIP_RECY: 20_000, SHIP_PF: 10_000}


@dataclass(frozen=True)
class HarvestJob:
    dest: Coords  # type Debris, pos 1..15 own DF ou 16 deep space
    total: int
    ship_id: int  # Recycler ou Pathfinder
    planet: Celestial
    moon: Celestial | None


def ships_for_payload(total: int, cargo_per: int) -> int:
    """Ceil(total / cargo); mínimo 1 se total > 0."""
    if total <= 0:
        return 0
    per = max(1, int(cargo_per))
    return max(1, math.ceil(int(total) / per))


def deep_space_offsets(split_active: bool, range_: int) -> list[int]:
    """Offsets de sistema p/ pos.16. Paridade TBot: -range .. range+1 se split."""
    if not split_active:
        return [0]
    r = max(0, int(range_))
    return list(range(-r, r + 2))


def moon_of(planet: Celestial, celestials: list[Celestial]) -> Celestial | None:
    g, s, p = planet.coords.galaxy, planet.coords.system, planet.coords.position
    for c in celestials:
        if c.coords.type != "Moon":
            continue
        if (
            c.coords.galaxy == g
            and c.coords.system == s
            and c.coords.position == p
        ):
            return c
    return None


def ship_count(ships: dict[int, dict[str, int]], sid: int) -> int:
    return int(ships.get(sid, {}).get("number") or 0)


def ship_cargo(ships: dict[int, dict[str, int]], sid: int) -> int:
    c = int(ships.get(sid, {}).get("cargo") or 0)
    return c if c > 0 else _DEFAULT_CARGO.get(sid, 20_000)


def harvest_en_route(page, dest: Coords) -> bool:
    """True se já há Harvest outbound p/ G:S:P."""
    rows = page.locator(f'tr.eventFleet[data-mission-type="{MISSION_HARVEST}"]')
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
        parts = [
            p for p in dest_txt.replace("[", "").replace("]", "").split(":") if p.strip()
        ]
        if len(parts) < 3:
            continue
        try:
            g, s, p = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if g == dest.galaxy and s == dest.system and p == dest.position:
            return True
    return False


def harvest_back_in(page) -> float | None:
    """Segundos até o Harvest mais próximo voltar (ou chegar)."""
    now = time.time()
    best: float | None = None
    rows = page.locator(f'tr.eventFleet[data-mission-type="{MISSION_HARVEST}"]')
    for i in range(rows.count()):
        el = rows.nth(i)
        arrival = el.get_attribute("data-arrival-time")
        if not arrival or not arrival.isdigit():
            continue
        eta = int(arrival) - now
        if eta < 0:
            continue
        if best is None or eta < best:
            best = float(eta)
    return best


def _cache_debris(
    page, keys: set[tuple[int, int]], cache: dict[tuple[int, int], list[DebrisField]]
) -> None:
    for g, s in keys:
        if (g, s) in cache:
            continue
        cache[(g, s)] = fetch_debris_near(page, g, s, radius=0)


def collect_jobs(
    page,
    celestials: list[Celestial],
    *,
    harvest_own: bool,
    harvest_ds: bool,
    min_own: int,
    min_ds: int,
    split_active: bool,
    split_range: int,
    n_systems: int = 499,
) -> list[HarvestJob]:
    planets = [c for c in celestials if c.coords.type == "Planet"]
    need: set[tuple[int, int]] = set()
    for pl in planets:
        g, s = pl.coords.galaxy, pl.coords.system
        if harvest_own:
            need.add((g, s))
        if harvest_ds:
            for off in deep_space_offsets(split_active, split_range):
                need.add((g, clamp_system(s + off, n_systems)))

    cache: dict[tuple[int, int], list[DebrisField]] = {}
    _cache_debris(page, need, cache)

    jobs: list[HarvestJob] = []
    seen: set[tuple[int, int, int]] = set()

    for pl in planets:
        moon = moon_of(pl, celestials)
        g, s, p = pl.coords.galaxy, pl.coords.system, pl.coords.position

        if harvest_own:
            key = (g, s, p)
            if key not in seen:
                for df in cache.get((g, s), []):
                    if df.coords.position != p:
                        continue
                    if df.total < min_own:
                        continue
                    seen.add(key)
                    jobs.append(
                        HarvestJob(
                            dest=Coords(g, s, p, "Debris"),
                            total=df.total,
                            ship_id=SHIP_RECY,
                            planet=pl,
                            moon=moon,
                        )
                    )
                    break

        if harvest_ds:
            for off in deep_space_offsets(split_active, split_range):
                sys = clamp_system(s + off, n_systems)
                key = (g, sys, 16)
                if key in seen:
                    continue
                for df in cache.get((g, sys), []):
                    if df.coords.position != 16:
                        continue
                    if df.total < min_ds:
                        continue
                    seen.add(key)
                    jobs.append(
                        HarvestJob(
                            dest=Coords(g, sys, 16, "Debris"),
                            total=df.total,
                            ship_id=SHIP_PF,
                            planet=pl,
                            moon=moon,
                        )
                    )
                    break
    return jobs


def pick_origin(job: HarvestJob, page) -> tuple[Celestial, int] | None:
    """Prefere lua com naves; senão planeta. Retorna (origin, available)."""
    candidates: list[Celestial] = []
    if job.moon is not None:
        candidates.append(job.moon)
    candidates.append(job.planet)
    for origin in candidates:
        switch_celestial(page, origin)
        open_component(page, "fleetdispatch")
        ships = parse_ships(page)
        n = ship_count(ships, job.ship_id)
        if n > 0:
            return origin, n
    return None


class AutoHarvestWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        cfg = settings.get("AutoHarvest") or {}
        if not cfg.get("Active"):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        leave = int(ctx.get("slots_to_leave_free") or 1)
        wait = random.uniform(self.interval_min, self.interval_max)
        tui = ctx.get("tui")
        refresh = ctx.get("refresh")

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        harvest_own = bool(cfg.get("HarvestOwnDF", True))
        harvest_ds = bool(cfg.get("HarvestDeepSpace", True))
        min_own = int(cfg.get("MinimumResourcesOwnDF") or 300)
        min_ds = int(cfg.get("MinimumResourcesDeepSpace") or 50_000)

        expo = settings.get("Expeditions") or {}
        split = expo.get("SplitExpeditionsBetweenSystems") or {}
        split_active = bool(split.get("Active"))
        split_range = int(split.get("Range") or 1)

        celestials = parse_celestials(page)
        if not celestials:
            self._next_wait = random.uniform(30, 90)
            self.reason = "planetList vazio"
            return "retry DOM"

        jobs = collect_jobs(
            page,
            celestials,
            harvest_own=harvest_own,
            harvest_ds=harvest_ds,
            min_own=min_own,
            min_ds=min_ds,
            split_active=split_active,
            split_range=split_range,
        )
        if not jobs:
            self._next_wait = wait
            self.reason = "sem DF"
            return self.reason

        sent = 0
        skipped = 0
        for job in jobs:
            if harvest_en_route(page, job.dest):
                skipped += 1
                continue

            open_component(page, "fleetdispatch")
            slots = fleet_slots(page)
            if slots.total <= 0:
                self._next_wait = random.uniform(30, 90)
                self.reason = "slots DOM 0/0"
                _log("harvest: parse slots falhou (0/0)", "warn")
                return self.reason
            if not slots_available(slots, leave):
                back = harvest_back_in(page)
                self._next_wait = (back + random.uniform(5, 20)) if back else wait
                self.reason = f"sem slot · enviou {sent}"
                if sent == 0:
                    self.reason = f"sem slot frota ({slots.free}/{slots.total})"
                return self.reason

            picked = pick_origin(job, page)
            if picked is None:
                skipped += 1
                tag = f"{job.dest.galaxy}:{job.dest.system}:{job.dest.position}"
                ship = "PF" if job.ship_id == SHIP_PF else "recy"
                _log(f"harvest: sem {ship} p/ {tag}", "warn")
                continue

            origin, available = picked
            ships = parse_ships(page)
            cargo = ship_cargo(ships, job.ship_id)
            need = ships_for_payload(job.total, cargo)
            n_send = min(need, available)
            if n_send <= 0:
                skipped += 1
                continue

            status = send_fleet(
                page,
                {job.ship_id: n_send},
                job.dest.galaxy,
                job.dest.system,
                job.dest.position,
                mission=MISSION_HARVEST,
                speed=10,
                dest_type=DEST_DEBRIS,
            )
            tag = f"{job.dest.galaxy}:{job.dest.system}:{job.dest.position}"
            ship = "PF" if job.ship_id == SHIP_PF else "recy"
            if status == "ok":
                sent += 1
                _log(
                    f"harvest: {origin.label}→{tag} {n_send}{ship} ({job.total})",
                    "ok",
                )
            else:
                skipped += 1
                _log(f"harvest: fail {status} → {tag}", "warn")
                if "slot" in status.lower():
                    back = harvest_back_in(page)
                    self._next_wait = (back + random.uniform(5, 20)) if back else wait
                    self.reason = f"sem slot · enviou {sent}"
                    return self.reason

        back = harvest_back_in(page) if sent else None
        self._next_wait = (back + random.uniform(5, 15)) if back else wait
        if sent:
            self.reason = f"{sent} sent · skip {skipped}"
        else:
            self.reason = f"nada · skip {skipped}" if skipped else "sem DF"
        return self.reason


if __name__ == "__main__":
    assert ships_for_payload(0, 20_000) == 0
    assert ships_for_payload(1, 20_000) == 1
    assert ships_for_payload(20_000, 20_000) == 1
    assert ships_for_payload(20_001, 20_000) == 2
    assert deep_space_offsets(False, 5) == [0]
    assert deep_space_offsets(True, 1) == [-1, 0, 1, 2]
    pl = Celestial("1", "P", Coords(1, 10, 6, "Planet"))
    mo = Celestial("2", "M", Coords(1, 10, 6, "Moon"))
    assert moon_of(pl, [pl, mo]) is mo
    assert moon_of(pl, [pl]) is None
    print("autoharvest ok")
