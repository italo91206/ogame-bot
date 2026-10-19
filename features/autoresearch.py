"""E08 AutoResearch: Target/lab + research_once + transport hook."""
from __future__ import annotations

import random
from typing import Any

from features.autoresearch_pick import (
    LAB,
    NAMES,
    label,
    lvl,
    next_level,
    pick_next,
    price,
)
from features.transports import (
    clamp_wait_to_incoming,
    send_miner_transport,
    transport_retry_wait,
    transports_enabled,
)
from game import (
    Celestial,
    build_technology,
    building_queue,
    current_resources,
    open_component,
    parse_celestials,
    format_cost,
    parse_ogame_int,
    parse_slots,
    parse_technologies,
    peek_tech_costs,
    research_countdown,
    research_queue,
    resource_production_per_hour,
    secs_until_resources,
    switch_celestial,
)
from runtime import Worker

_fmt_cost = format_cost


def _match_target(c: Celestial, target: dict) -> bool:
    if not target:
        return False
    return (
        int(target.get("Galaxy", -1)) == c.coords.galaxy
        and int(target.get("System", -1)) == c.coords.system
        and int(target.get("Position", -1)) == c.coords.position
        and (target.get("Type") or "Planet") == c.coords.type
    )


def resolve_target(page, cfg: dict) -> tuple[Celestial | None, int, str]:
    """(celestial, lab_level, why). Biggest lab if Target missing/invalid."""
    celestials = [c for c in parse_celestials(page) if c.coords.type == "Planet"]
    if not celestials:
        return None, 0, "sem planetas"

    target = cfg.get("Target") or {}
    hit = next((c for c in celestials if _match_target(c, target)), None)
    if hit is not None:
        switch_celestial(page, hit)
        open_component(page, "facilities")
        lab = lvl(parse_technologies(page), LAB)
        return hit, lab, "Target"

    best: Celestial | None = None
    best_lab = -1
    for c in celestials:
        switch_celestial(page, c)
        open_component(page, "facilities")
        lab = lvl(parse_technologies(page), LAB)
        if lab > best_lab:
            best, best_lab = c, lab
    return best, best_lab, "maior lab"


def _wait_for_resources(
    page, tid: int, cap_s: float, next_lvl: int | str
) -> tuple[float | None, str, str]:
    if "component=research" not in page.url:
        open_component(page, "research")
    lab = label(tid)
    cost = peek_tech_costs(page, tid)
    if not cost:
        return None, "custo indisponível", (
            f"quer {lab} → {next_lvl} mas custo indisponível na UI"
        )
    res = current_resources(page)
    have = {
        "metal": parse_ogame_int(res["metal"]),
        "crystal": parse_ogame_int(res["crystal"]),
        "deut": parse_ogame_int(res["deut"]),
    }
    prod = resource_production_per_hour(page)
    eta = secs_until_resources(cost, have, prod)
    stock = f"tem M{have['metal']} C{have['crystal']} D{have['deut']}"
    ph = (
        f"prod/h M{prod.get('metal', 0)} "
        f"C{prod.get('crystal', 0)} D{prod.get('deut', 0)}"
    )
    if eta is None:
        return None, "sem ETA", (
            f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; "
            f"{stock}; {ph}; produção insuficiente p/ ETA)"
        )
    jitter = random.uniform(5, 20)
    raw = eta + jitter
    if raw > cap_s:
        return (
            cap_s,
            f"ETA {eta:.0f}s capado em {cap_s:.0f}s",
            f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; "
            f"{stock}; {ph}; ETA {eta:.0f}s → espera cap {cap_s:.0f}s)",
        )
    return (
        raw,
        f"ETA {eta:.0f}s +folga",
        f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; "
        f"{stock}; {ph}; ETA {eta:.0f}s)",
    )


def research_once(
    page,
    cfg: dict,
    interval_max_s: float,
    *,
    prioritize_robots: bool = False,
    book=None,
    brain: dict | None = None,
    leave_slots: int = 1,
) -> tuple[str | None, float | None, str | None, str]:
    """(msg, wait_s, schedule_why, log_line). wait None → CheckInterval."""
    celestial, lab, how = resolve_target(page, cfg)
    if celestial is None:
        return None, None, "sem planeta", "sem planeta alvo"
    tag = celestial.label

    if lab <= 0:
        return None, None, "sem lab", f"{tag}: Research Lab ausente ({how})"

    switch_celestial(page, celestial)
    open_component(page, "facilities")
    bid, bcd = building_queue(page)
    if bid == LAB:
        wait = bcd + random.uniform(5, 15) if bcd > 0 else random.uniform(5, 20)
        return (
            "lab busy",
            wait,
            f"lab upgrade {bcd:.0f}s",
            f"{tag}: lab em upgrade ({bcd:.0f}s)",
        )

    open_component(page, "research")
    rid, rcd = research_queue(page)
    if rid:
        wait = rcd + random.uniform(5, 15) if rcd > 0 else random.uniform(5, 20)
        return (
            "busy",
            wait,
            f"pesquisa {rcd:.0f}s",
            f"{tag}: pesquisa em andamento ({rcd:.0f}s)",
        )

    techs = parse_technologies(page)
    slots = parse_slots(page)
    tid = pick_next(
        techs,
        cfg,
        lab,
        slots_total=slots.total,
        prioritize_robots=prioritize_robots,
        afford_techs=techs,
    )
    if tid is None:
        want = pick_next(
            techs,
            cfg,
            lab,
            slots_total=slots.total,
            prioritize_robots=prioritize_robots,
        )
        if want is None:
            return None, None, "nada sob cap", f"{tag}: nada sob cap / elegível"
        nxt = next_level(techs, want)
        wait, sched, detail = _wait_for_resources(page, want, interval_max_s, nxt)
        brain = brain or {}
        # E08-T05: ETA impossível ou > CheckIntervalMax → pedir Origin
        slow = wait is None or wait >= interval_max_s
        if slow and transports_enabled(brain, cfg):
            if "component=research" not in page.url:
                open_component(page, "research")
            cost = peek_tech_costs(page, want) or price(want, nxt)
            if cost:
                tr = send_miner_transport(
                    page, brain, celestial, cost, leave_slots=leave_slots
                )
                if tr.startswith("ok") or tr == "incoming":
                    twait, tsched = transport_retry_wait(page, celestial)
                    return (
                        f"transport {NAMES.get(want, want)}",
                        twait,
                        tsched or f"transport → {label(want)}→{nxt}",
                        f"{tag}: transport {tr} p/ {label(want)}→{nxt}",
                    )
                detail = f"{detail}; transport: {tr}"
        wait, arr = clamp_wait_to_incoming(page, celestial, wait)
        if arr:
            sched = arr
        return (
            f"wait {NAMES.get(want, want)}",
            wait,
            sched,
            f"{tag}: {detail}",
        )

    cost = peek_tech_costs(page, tid) or price(tid, next_level(techs, tid))
    cur = lvl(techs, tid)
    nxt = cur + 1
    lab_name = label(tid)
    fail = build_technology(page, tid)
    if fail:
        return (
            f"fail {NAMES.get(tid, tid)}",
            90.0,
            "retry 90s",
            f"{tag}: recursos ok p/ {lab_name} {cur}→{nxt}, mas click falhou "
            f"({fail}) — retry 90s",
        )
    if book is not None and cost:
        book.spend(celestial.id, cost)
    cd = research_countdown(page)
    if cd > 0:
        wait = cd + random.uniform(5, 15)
        sched = f"countdown {cd:.0f}s"
    else:
        wait = random.uniform(20, 45)
        sched = "pós-research 20–45s"
    return (
        f"{NAMES.get(tid, tid)}→{nxt}",
        wait,
        sched,
        f"{tag}: recursos disponíveis, {lab_name} {cur}→{nxt} "
        f"({_fmt_cost(cost)}) [{how}]",
    )


class AutoResearchWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        brain = settings.get("Brain") or {}
        cfg = brain.get("AutoResearch") or {}
        if not brain.get("Active") or not cfg.get("Active"):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        am = brain.get("AutoMine") or {}
        prioritize_robots = bool(am.get("PrioritizeRobotsAndNanites"))
        leave = int((settings.get("General") or {}).get("SlotsToLeaveFree") or 1)
        tui = ctx.get("tui")
        refresh = ctx.get("refresh")
        lo_m, hi_m = self.interval_min / 60, self.interval_max / 60

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        try:
            result, wait, why, line = research_once(
                page,
                cfg,
                self.interval_max,
                prioritize_robots=prioritize_robots,
                book=ctx.get("resources"),
                brain=brain,
                leave_slots=leave,
            )
        except Exception as e:
            err = str(e).split("\n", 1)[0][:100]
            _log(f"autoresearch: erro UI ({err}) — retry 90s", "warn")
            self._next_wait = 90.0
            self.reason = "erro UI"
            return "erro UI"

        lvl_log = "ok" if result and "→" in (result or "") else "info"
        if result and str(result).startswith("fail"):
            lvl_log = "warn"
        _log(f"autoresearch: {line}", lvl_log)

        if wait is not None and why:
            self._next_wait = wait
            self.reason = why
            _log(f"autoresearch: próxima decisão em {wait:.0f}s — {why}")
        else:
            wait_s = random.uniform(self.interval_min, self.interval_max)
            self._next_wait = wait_s
            self.reason = f"nada urgente (CheckInterval {lo_m:.0f}–{hi_m:.0f}min)"
            _log(f"autoresearch: próxima decisão em {wait_s:.0f}s — {self.reason}")

        if result and "→" in result:
            return result
        if result:
            return str(result)
        return "nada"


if __name__ == "__main__":
    from features.autoresearch_pick import ENERGY, COMBUSTION, pick_next
    from game import Tech, secs_until_resources

    assert pick_next(
        {ENERGY: Tech(ENERGY, 0, "on")},
        {"OptimizeForStart": True, "MaxEnergyTechnology": 20, "MaxCombustionDrive": 19,
         "MaxLaserTechnology": 12, "MaxIonTechnology": 5, "MaxHyperspaceTechnology": 20,
         "MaxPlasmaTechnology": 20, "MaxImpulseDrive": 17, "MaxHyperspaceDrive": 15,
         "MaxEspionageTechnology": 8, "MaxComputerTechnology": 20, "MaxAstrophysics": 23,
         "MaxIntergalacticResearchNetwork": 12, "MaxWeaponsTechnology": 25,
         "MaxShieldingTechnology": 25, "MaxArmourTechnology": 25},
        lab=1,
    ) == ENERGY
    assert secs_until_resources(
        {"metal": 1000, "crystal": 0, "deut": 0},
        {"metal": 0, "crystal": 0, "deut": 0},
        {"metal": 3600, "crystal": 0, "deut": 0},
    ) == 1000
    print("autoresearch ok")
