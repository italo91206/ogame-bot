"""E09 Brain AutoCargo: build cargos up to keep/capacity caps."""
from __future__ import annotations

import math
import random
import re
from typing import Any

from game import (
    Celestial,
    building_queue,
    current_resources,
    open_component,
    parse_celestials,
    parse_ogame_int,
    switch_celestial,
)
from game.attacks import count_own_ships_in_flight
from game.fleet import NAME_TO_ID, has_incoming_transport, parse_ships
from game.tech import build_ships, peek_tech_costs
from runtime import Worker

SHIPYARD_ID, NANITES_ID = 21, 15


def _match(c: Celestial, e: dict) -> bool:
    return (
        c.coords.galaxy == int(e.get("Galaxy", -1))
        and c.coords.system == int(e.get("System", -1))
        and c.coords.position == int(e.get("Position", -1))
        and c.coords.type == (e.get("Type") or "Planet")
    )


def _excluded(c: Celestial, exclude: list) -> bool:
    return any(_match(c, e) for e in (exclude or []))


def unit_cargo(ships: dict[int, dict[str, int]], sid: int) -> int:
    c = int(ships.get(sid, {}).get("cargo") or 0)
    if c > 0:
        return c
    return 25000 if sid == 203 else 5000


def fleet_capacity(ships: dict[int, dict[str, int]]) -> int:
    total = 0
    for sid, info in ships.items():
        n = int(info.get("number") or 0)
        if n <= 0:
            continue
        cap = int(info.get("cargo") or 0) or unit_cargo(ships, sid)
        total += n * cap
    return total


def needed_cargos(
    have: int,
    *,
    max_keep: int,
    max_build: int,
    limit_to_capacity: bool,
    fleet_cap: int,
    total_res: int,
    cargo_per: int,
) -> int:
    """TBot AutoCargo neededCargos (before afford clamp)."""
    keep = max(0, int(max_keep))
    build_cap = max(0, int(max_build))
    have = max(0, int(have))
    if limit_to_capacity and cargo_per > 0 and fleet_cap <= total_res:
        diff = max(0, int(total_res) - int(fleet_cap))
        need = int(math.ceil(diff / float(cargo_per)))
    else:
        need = keep - have
    if need <= 0:
        return 0
    need = min(need, build_cap)
    if have + need > keep:
        need = max(0, keep - have)
    return need


def afford_ships(cost_one: dict[str, int], have: dict[str, int], want: int) -> int:
    if want <= 0:
        return 0
    n = want
    for key in ("metal", "crystal", "deut"):
        unit = int(cost_one.get(key) or 0)
        if unit <= 0:
            continue
        n = min(n, int(have.get(key, 0)) // unit)
    return max(0, n)


def shipyard_producing(page) -> bool:
    """True if shipyard has active/queued production.

    `#shipyardCountdown` often shows `load...` until JS paints — that is busy,
    not idle (treating it as idle caused rebuild loops).
    """
    if page.locator("div.shipSumCount").count():
        return True
    loc = page.locator("#shipyardCountdown")
    if not loc.count():
        return False
    txt = (loc.first.inner_text() or "").strip().lower()
    if not txt or txt in ("-", "—", "0"):
        return False
    if txt == "load...":
        return True
    return any(ch.isdigit() for ch in txt)


def ships_in_shipyard_queue(page, tech_id: int) -> int:
    """Count tech_id in active construction + table.queue (shipyard page)."""
    return parse_ships_in_shipyard_html(page.content(), int(tech_id))


def parse_ships_in_shipyard_html(html: str, tech_id: int) -> int:
    """Pure parse of shipyard HTML → how many of tech_id are building/queued."""
    tid = int(tech_id)
    n = 0
    m = re.search(
        rf"openTech={tid}[\s\S]{{0,500}}?shipSumCount[^>]*>([^<]+)",
        html,
    )
    if m:
        n += parse_ogame_int(m.group(1))
    for m in re.finditer(
        rf'alt="techId_{tid}"[\s\S]{{0,120}}?<br\s*/?>\s*([\d.\s]+)',
        html,
        flags=re.I,
    ):
        n += parse_ogame_int(m.group(1))
    return n


def cargo_celestial(
    page, celestial: Celestial, cfg: dict
) -> tuple[str | None, str]:
    """(short_result, log_line). None result = skip/noop."""
    switch_celestial(page, celestial)
    open_component(page, "shipyard")

    if shipyard_producing(page):
        return None, "estaleiro ocupado"

    bid, _ = building_queue(page)
    if bid in (SHIPYARD_ID, NANITES_ID):
        return None, f"upgrade {bid} em curso"

    if cfg.get("SkipIfIncomingTransport", True) and has_incoming_transport(
        page,
        celestial.coords.galaxy,
        celestial.coords.system,
        celestial.coords.position,
        moon=celestial.coords.type == "Moon",
    ):
        return None, "transport incoming"

    cargo_name = str(cfg.get("CargoType") or "LargeCargo")
    sid = NAME_TO_ID.get(cargo_name) or NAME_TO_ID["LargeCargo"]
    ships = parse_ships(page)
    local_n = int(ships.get(sid, {}).get("number") or 0)
    # MaxKeep must include in-flight (expo drains hangar → rebuild loop)
    flight_n = count_own_ships_in_flight(
        page,
        sid,
        celestial.coords.galaxy,
        celestial.coords.system,
        celestial.coords.position,
        moon=celestial.coords.type == "Moon",
    )
    have_n = local_n + flight_n
    per = unit_cargo(ships, sid)
    cap = fleet_capacity(ships)  # local only — LimitToCapacity = evacuate this planet
    res = current_resources(page)
    have_res = {
        "metal": parse_ogame_int(res.get("metal", "0")),
        "crystal": parse_ogame_int(res.get("crystal", "0")),
        "deut": parse_ogame_int(res.get("deut", "0")),
    }
    total_res = have_res["metal"] + have_res["crystal"] + have_res["deut"]
    need = needed_cargos(
        have_n,
        max_keep=int(cfg.get("MaxCargosToKeep") or 0),
        max_build=int(cfg.get("MaxCargosToBuild") or 0),
        limit_to_capacity=bool(cfg.get("LimitToCapacity")),
        fleet_cap=cap,
        total_res=total_res,
        cargo_per=per,
    )
    if need <= 0:
        note = f"{have_n} {cargo_name}"
        if flight_n:
            note += f" (local {local_n}+flight {flight_n})"
        return None, f"ok ({note}, cap {cap})"

    cost = peek_tech_costs(page, sid) or {}
    build_n = afford_ships(cost, have_res, need)
    if build_n <= 0:
        return None, f"sem recurso p/ {need}x{cargo_name}"

    fail = build_ships(page, sid, build_n)
    if fail:
        return f"fail {cargo_name}", f"build falhou ({fail})"
    note = f"{build_n}x{cargo_name}" + (f" (pedido {need})" if build_n < need else "")
    return note, f"construiu {note}"


class AutoCargoWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        brain = settings.get("Brain") or {}
        cfg = brain.get("AutoCargo") or {}
        if not (brain.get("Active") and cfg.get("Active")):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        tui = ctx.get("tui")
        refresh = ctx.get("refresh")

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        celestials = parse_celestials(page)
        if not celestials:
            self._next_wait = random.uniform(30, 90)
            self.reason = "planetList vazio"
            return "retry DOM"

        exclude = cfg.get("Exclude") or []
        exclude_moons = bool(cfg.get("ExcludeMoons", True))
        todo = [
            c
            for c in celestials
            if not _excluded(c, exclude)
            and not (exclude_moons and c.coords.type == "Moon")
        ]
        if cfg.get("RandomOrder"):
            random.shuffle(todo)

        built: list[str] = []
        for c in todo:
            tag = c.label
            try:
                result, line = cargo_celestial(page, c, cfg)
            except Exception as e:
                err = str(e).split("\n", 1)[0][:100]
                _log(f"autocargo {tag}: erro UI ({err})", "warn")
                continue
            lvl = "ok" if result and "x" in result else "info"
            if result and str(result).startswith("fail"):
                lvl = "warn"
            _log(f"autocargo {tag}: {line}", lvl)
            if result and not str(result).startswith("fail"):
                built.append(f"{tag} {result}")

        wait = random.uniform(self.interval_min, self.interval_max)
        self._next_wait = wait
        self.reason = (
            f"build {', '.join(built[:3])}" if built else "nada a construir"
        )
        return self.reason


if __name__ == "__main__":
    from game.attacks import count_own_ships_in_flight_html

    assert needed_cargos(
        10,
        max_keep=50,
        max_build=50,
        limit_to_capacity=False,
        fleet_cap=0,
        total_res=0,
        cargo_per=25000,
    ) == 40
    assert needed_cargos(
        10,
        max_keep=50,
        max_build=5,
        limit_to_capacity=False,
        fleet_cap=0,
        total_res=0,
        cargo_per=25000,
    ) == 5
    assert needed_cargos(
        0,
        max_keep=100,
        max_build=100,
        limit_to_capacity=True,
        fleet_cap=50_000,
        total_res=150_000,
        cargo_per=25_000,
    ) == 4
    # local empty + 180 in flight → keep 200 → only 20 more (not rebuild to 200)
    assert needed_cargos(
        180,
        max_keep=200,
        max_build=50,
        limit_to_capacity=True,
        fleet_cap=0,
        total_res=50_000_000,
        cargo_per=25_000,
    ) == 20
    assert afford_ships(
        {"metal": 6000, "crystal": 6000, "deut": 0},
        {"metal": 20_000, "crystal": 15_000, "deut": 0},
        10,
    ) == 2
    # active 12x202 + queue 5+5x202 (sample shipyard_queue)
    sy_html = """
    <a href="...?openTech=202"><img alt="techId_202"/></a>
    <div class="shipSumCount" id="shipSumCount7">12</div>
    <span id="shipyardCountdown">load...</span>
    <table class="queue"><tr>
      <td><img alt="techId_202"/><br/>5</td>
      <td><img alt="techId_203"/><br/>3</td>
      <td><img alt="techId_202"/><br/>5</td>
      <td><img alt="techId_208"/><br/>2</td>
    </tr></table>
    """
    assert parse_ships_in_shipyard_html(sy_html, 202) == 22
    assert parse_ships_in_shipyard_html(sy_html, 208) == 2
    assert parse_ships_in_shipyard_html(sy_html, 203) == 3
    sample = """
    <tr class="eventFleet" id="eventRow-1" data-mission-type="15" data-return-flight="false">
    <td class="countDown">x</td>
    <td class="coordsOrigin"><a>[1:77:6]</a></td>
    <td class="originFleet"><figure class="planetIcon planet"></figure></td>
    <td class="icon_movement"><span title="&lt;table class=&quot;fleetinfo&quot;&gt;
    &lt;tr&gt;&lt;td&gt;Large Cargo:&lt;/td&gt;&lt;td class=&quot;value&quot;&gt;100&lt;/td&gt;&lt;/tr&gt;
    &lt;/table&gt;"></span></td>
    <td class="destFleet"><figure class="planetIcon planet"></figure></td>
    <td class="destCoords"><a>[1:77:16]</a></td>
    </tr>
    <tr class="eventFleet" id="eventRow-2" data-mission-type="15" data-return-flight="true">
    <td class="countDown">x</td>
    <td class="coordsOrigin"><a>[1:77:16]</a></td>
    <td class="originFleet"><figure class="planetIcon planet"></figure></td>
    <td class="icon_movement"><span title="&lt;table class=&quot;fleetinfo&quot;&gt;
    &lt;tr&gt;&lt;td&gt;Cargueiro Grande:&lt;/td&gt;&lt;td class=&quot;value&quot;&gt;80&lt;/td&gt;&lt;/tr&gt;
    &lt;/table&gt;"></span></td>
    <td class="destFleet"><figure class="planetIcon planet"></figure></td>
    <td class="destCoords"><a>[1:77:6]</a></td>
    </tr>
    <tr class="eventFleet" id="eventRow-3" data-mission-type="1" data-return-flight="false">
    <td class="countDown hostile">x</td>
    <td class="coordsOrigin"><a>[1:77:6]</a></td>
    <td class="originFleet"><figure class="planetIcon planet"></figure></td>
    <td class="icon_movement"><span title="&lt;table class=&quot;fleetinfo&quot;&gt;
    &lt;tr&gt;&lt;td&gt;Large Cargo:&lt;/td&gt;&lt;td&gt;999&lt;/td&gt;&lt;/tr&gt;
    &lt;/table&gt;"></span></td>
    <td class="destCoords"><a>[1:1:1]</a></td>
    </tr>
    """
    assert count_own_ships_in_flight_html(sample, 203, 1, 77, 6) == 180
    print("autocargo ok")
