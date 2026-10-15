"""E05 AutoMine: build under caps; UI filters affordability (data-status=on)."""
from __future__ import annotations

import random
from typing import Any

from features.autocargo import afford_ships, shipyard_producing
from features.automine_pick import (
    FACILITY_IDS,
    NAMES,
    SAT_ID,
    SHIPYARD,
    avg_temp_from_title,
    excluded,
    label,
    needed_sats,
    pick_next,
    pick_why,
)
from game import (
    Celestial,
    Tech,
    build_technology,
    building_countdown,
    building_queue,
    current_resources,
    open_component,
    parse_celestials,
    format_cost,
    parse_ogame_int,
    parse_technologies,
    peek_tech_costs,
    resource_production_per_hour,
    secs_until_resources,
    switch_celestial,
)
from game.tech import build_ships
from runtime import Worker, pick_schedule, schedule_why
from features.transports import send_miner_transport, transports_enabled

_fmt_cost = format_cost


def _pad_moon_deut(cost: dict[str, int], cfg: dict, moon: bool) -> dict[str, int]:
    """TBot: xCostBuildable.Deuterium += DeutToLeaveOnMoons (ETA / afford / transport)."""
    if not cost or not moon:
        return cost
    leave = int(cfg.get("DeutToLeaveOnMoons") or 0)
    if leave <= 0:
        return cost
    out = {k: int(cost.get(k) or 0) for k in ("metal", "crystal", "deut")}
    out["deut"] += leave
    return out


def _have_resources(have: dict[str, int], cost: dict[str, int]) -> bool:
    return all(
        int(have.get(k) or 0) >= int(cost.get(k) or 0)
        for k in ("metal", "crystal", "deut")
    )


def _current_have(page) -> dict[str, int]:
    res = current_resources(page)
    return {
        "metal": parse_ogame_int(res["metal"]),
        "crystal": parse_ogame_int(res["crystal"]),
        "deut": parse_ogame_int(res["deut"]),
    }


def _busy_wait(page) -> tuple[str | None, float | None, str | None, str] | None:
    """If building queue busy (TBot BuildingID!=0), return mine_celestial tuple."""
    bid, cd = building_queue(page)
    if not bid:
        return None
    # ponytail: cd==0 → retry curto (TBot SomeSeconds), nunca CheckInterval
    wait = cd + random.uniform(5, 15) if cd > 0 else random.uniform(5, 20)
    why = (
        f"upgrade em progresso ({cd:.0f}s)"
        if cd > 0
        else "upgrade em progresso (sem countdown)"
    )
    line = (
        f"fila ocupada — {why}"
        if cd > 0
        else f"fila ocupada (id={bid}, sem secs), retry {wait:.0f}s"
    )
    return "busy", wait, why, line


def _wait_for_resources(
    page,
    tid: int,
    cap_s: float,
    next_lvl: int | str,
    *,
    cfg: dict | None = None,
    moon: bool = False,
    cost: dict[str, int] | None = None,
) -> tuple[float | None, str, str]:
    """(secs, schedule_why, log_line). cost pré-pad opcional (lua / transport)."""
    need = "facilities" if tid in FACILITY_IDS else "supplies"
    if f"component={need}" not in page.url:
        open_component(page, need)
    lab = label(tid)
    if cost is None:
        cost = peek_tech_costs(page, tid)
    if cost and cfg is not None:
        cost = _pad_moon_deut(cost, cfg, moon)
    if not cost:
        return None, f"faltam recursos ({lab}→{next_lvl}, custo indisponível)", (
            f"quer {lab} → {next_lvl} mas custo indisponível na UI"
        )
    have = _current_have(page)
    prod = resource_production_per_hour(page)
    eta = secs_until_resources(cost, have, prod)
    stock = f"tem M{have['metal']} C{have['crystal']} D{have['deut']}"
    ph = (
        f"prod/h M{prod.get('metal', 0)} "
        f"C{prod.get('crystal', 0)} D{prod.get('deut', 0)}"
    )
    if eta is None:
        return None, f"faltam recursos ({lab}→{next_lvl}, sem ETA)", (
            f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; "
            f"{stock}; {ph}; produção insuficiente p/ ETA)"
        )
    jitter = random.uniform(5, 20)
    raw = eta + jitter
    if raw > cap_s:
        return (
            cap_s,
            f"faltam recursos ({lab}→{next_lvl}, ETA {eta:.0f}s→cap {cap_s:.0f}s)",
            f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; "
            f"{stock}; {ph}; ETA {eta:.0f}s → espera cap {cap_s:.0f}s)",
        )
    return (
        raw,
        f"faltam recursos ({lab}→{next_lvl}, ETA {eta:.0f}s)",
        f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; "
        f"{stock}; {ph}; ETA {eta:.0f}s)",
    )


def _planet_avg_temp(page) -> float:
    for sel in ("#planetList a.planetlink.active", "#planetList a.moonlink.active"):
        loc = page.locator(sel)
        if loc.count():
            return avg_temp_from_title(loc.first.get_attribute("title") or "")
    return 0.0


def _mine_sats(
    page,
    celestial: Celestial,
    energy: int,
    cfg: dict,
    interval_max_s: float,
    brain: dict | None,
    leave_slots: int,
) -> tuple[str | None, float | None, str | None, str]:
    open_component(page, "shipyard")
    if shipyard_producing(page):
        wait = random.uniform(30, 90)
        return "busy", wait, "estaleiro ocupado", "estaleiro ocupado (sats)"
    bid, cd = building_queue(page)
    if bid == SHIPYARD:
        wait = cd + random.uniform(5, 15) if cd > 0 else random.uniform(20, 45)
        return "busy", wait, "upgrade hangar", "hangar em upgrade — adia sats"

    n = needed_sats(energy, _planet_avg_temp(page))
    if n <= 0:
        return None, None, "energia ok", "sats: energia já >= 0"
    why = f"energia {energy} → sats"
    cost1 = peek_tech_costs(page, SAT_ID) or {}
    res = current_resources(page)
    have = {
        "metal": parse_ogame_int(res.get("metal", "0")),
        "crystal": parse_ogame_int(res.get("crystal", "0")),
        "deut": parse_ogame_int(res.get("deut", "0")),
    }
    build_n = afford_ships(cost1, have, n) if cost1 else 0
    if build_n <= 0:
        total = {k: int(cost1.get(k) or 0) * n for k in ("metal", "crystal", "deut")}
        prod = resource_production_per_hour(page)
        eta = secs_until_resources(total, have, prod) if cost1 else None
        brain = brain or {}
        if (eta is None or eta >= interval_max_s) and transports_enabled(brain, cfg):
            if total:
                tr = send_miner_transport(
                    page, brain, celestial, total, leave_slots=leave_slots
                )
                if tr.startswith("ok"):
                    return (
                        f"transport {n}xSat",
                        random.uniform(60, 120),
                        f"transport → {n} sats",
                        f"transport {tr} p/ {n} sats [{why}]",
                    )
        wait = (
            min(interval_max_s, eta + random.uniform(5, 20))
            if eta is not None
            else None
        )
        sched = f"faltam recursos ({n} sats)"
        return (
            f"wait {n}xSat",
            wait,
            sched,
            f"sem recurso p/ {n} sats ({_fmt_cost(total)}) [{why}]",
        )

    fail = build_ships(page, SAT_ID, build_n)
    if fail:
        return (
            f"fail Sat×{build_n}",
            90.0,
            f"click falhou ({build_n} sats)",
            f"sats click falhou ({fail}) — retry 90s [{why}]",
        )
    note = f"{build_n} sats" + (f" (pedido {n})" if build_n < n else "")
    return (
        f"Sat×{build_n}",
        random.uniform(20, 45),
        f"sats iniciados ({note})",
        f"construiu {note} ({_fmt_cost({k: int(cost1.get(k) or 0) * build_n for k in ('metal', 'crystal', 'deut')})}) [{why}]",
    )


def mine_celestial(
    page,
    celestial: Celestial,
    cfg: dict,
    interval_max_s: float,
    book=None,
    brain: dict | None = None,
    leave_slots: int = 1,
) -> tuple[str | None, float | None, str | None, str]:
    """(msg, wait_s, schedule_why, log_line). wait None → CheckInterval."""
    moon = celestial.coords.type == "Moon"
    switch_celestial(page, celestial)

    open_component(page, "supplies" if not moon else "facilities")
    if (busy := _busy_wait(page)) is not None:
        return busy

    techs = parse_technologies(page)
    energy = parse_ogame_int(current_resources(page)["energy"])

    if not moon:
        open_component(page, "facilities")
        if (busy := _busy_wait(page)) is not None:
            return busy
        techs.update(parse_technologies(page))

    tid = pick_next(techs, cfg, moon, energy)
    if tid == SAT_ID:
        return _mine_sats(
            page, celestial, energy, cfg, interval_max_s, brain, leave_slots
        )

    # UI status=on ignora reserva; em lua exige cost+DeutToLeaveOnMoons (TBot).
    hold_for_deut: int | None = None
    if tid is not None and moon:
        need = "facilities"
        if f"component={need}" not in page.url:
            open_component(page, need)
        raw = peek_tech_costs(page, tid) or {}
        need_cost = _pad_moon_deut(raw, cfg, True)
        if need_cost and not _have_resources(_current_have(page), need_cost):
            hold_for_deut = tid
            tid = None

    if tid is None:
        want = hold_for_deut or pick_next(techs, cfg, moon, energy, afford=False)
        if want == SAT_ID:
            return _mine_sats(
                page, celestial, energy, cfg, interval_max_s, brain, leave_slots
            )
        if want is None:
            return None, None, "nada sob cap", "nada sob cap / affordável"
        nxt = (techs[want].level + 1) if want in techs else "?"
        why = pick_why(want, techs, cfg, moon, energy)
        wait, sched, detail = _wait_for_resources(
            page, want, interval_max_s, nxt, cfg=cfg, moon=moon
        )
        brain = brain or {}
        # E05-T10: ETA impossível ou > CheckIntervalMax → pedir Origin
        slow = wait is None or wait >= interval_max_s
        if slow and transports_enabled(brain, cfg):
            need = "facilities" if want in FACILITY_IDS else "supplies"
            if f"component={need}" not in page.url:
                open_component(page, need)
            cost = _pad_moon_deut(peek_tech_costs(page, want) or {}, cfg, moon)
            if cost:
                tr = send_miner_transport(
                    page, brain, celestial, cost, leave_slots=leave_slots
                )
                if tr.startswith("ok"):
                    lab = label(want)
                    return (
                        f"transport {NAMES.get(want, want)}",
                        random.uniform(60, 120),
                        f"transport → {lab}→{nxt}",
                        f"transport {tr} p/ {lab}→{nxt} [{why}]",
                    )
                detail = f"{detail}; transport: {tr}"
        return (
            f"wait {NAMES.get(want, want)}",
            wait,
            sched,
            f"{detail} [{why}]",
        )

    need = "facilities" if (moon or tid in FACILITY_IDS) else "supplies"
    if f"component={need}" not in page.url:
        open_component(page, need)

    cost = peek_tech_costs(page, tid) or {}
    why = pick_why(tid, techs, cfg, moon, energy)
    cur = techs[tid].level if tid in techs else "?"
    nxt = (cur + 1) if isinstance(cur, int) else "?"
    lab = label(tid)
    fail = build_technology(page, tid)
    if fail:
        return (
            f"fail {NAMES.get(tid, tid)}",
            90.0,
            f"click falhou ({lab} {cur}→{nxt})",
            f"recursos ok p/ {lab} {cur}→{nxt}, mas click falhou ({fail}) "
            f"— retry 90s [{why}]",
        )
    if book is not None and cost:
        book.spend(celestial.id, cost)
    cd = building_countdown(page)
    if cd > 0:
        wait = cd + random.uniform(5, 15)
        sched = f"upgrade em progresso ({lab} {cur}→{nxt}, {cd:.0f}s)"
    else:
        wait = random.uniform(20, 45)
        sched = f"upgrade iniciado ({lab} {cur}→{nxt}, sem countdown)"
    return (
        f"{NAMES.get(tid, tid)}→{nxt}",
        wait,
        sched,
        f"recursos disponíveis, {lab} {cur}→{nxt} ({_fmt_cost(cost)}) [{why}]",
    )


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
            # wait None (sem ETA / nada sob cap) → ainda agenda CheckInterval c/ motivo real
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
    assert _pad_moon_deut({"metal": 1, "crystal": 2, "deut": 3}, {}, False)["deut"] == 3
    assert _pad_moon_deut(
        {"metal": 1, "crystal": 2, "deut": 3}, {"DeutToLeaveOnMoons": 100}, True
    )["deut"] == 103
    assert _have_resources(
        {"metal": 10, "crystal": 10, "deut": 50},
        _pad_moon_deut({"metal": 1, "crystal": 1, "deut": 1}, {"DeutToLeaveOnMoons": 40}, True),
    )
    assert not _have_resources(
        {"metal": 10, "crystal": 10, "deut": 30},
        _pad_moon_deut({"metal": 1, "crystal": 1, "deut": 1}, {"DeutToLeaveOnMoons": 40}, True),
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
