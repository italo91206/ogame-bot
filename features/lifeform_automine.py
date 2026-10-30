"""E06 Lifeform AutoMine: worker + I/O (pick em `lifeform_automine_pick`)."""
from __future__ import annotations

import random
from typing import Any

from features.lifeform_automine_pick import (
    excluded,
    is_lf_building,
    lf_beats_mine,
    pick_next,
    slot_of,
)
from features.transport_bundle import KIND_LF_BUILD, send_bundled_transport
from features.transports import (
    clamp_wait_to_incoming,
    transport_retry_wait,
    transports_enabled,
)
from game import (
    Celestial,
    build_technology,
    building_queue,
    current_resources,
    lf_building_countdown,
    lf_building_queue,
    lf_research_queue,
    open_component,
    parse_celestials,
    format_cost,
    parse_ogame_int,
    parse_population,
    parse_technologies,
    peek_tech_costs,
    resource_production_per_hour,
    secs_until_resources,
    switch_celestial,
)
from runtime import Worker, pick_schedule, schedule_why

CRYSTAL = 2
ROBOTS, NANITES = 14, 15
METAL, DEUT = 1, 3

_fmt_cost = format_cost


def _busy_wait(page) -> tuple[str | None, float | None, str | None, str] | None:
    bid, cd = lf_building_queue(page)
    if bid:
        wait = cd + random.uniform(5, 15) if cd > 0 else random.uniform(5, 20)
        why = f"LF obra {cd:.0f}s" if cd > 0 else "LF obra ~0s"
        return "busy", wait, why, f"fila LF ocupada ({cd:.0f}s)"
    cid, ccd = building_queue(page)
    if cid in (ROBOTS, NANITES):
        wait = ccd + random.uniform(5, 15) if ccd > 0 else random.uniform(5, 20)
        return (
            "busy",
            wait,
            f"robots/nanites {ccd:.0f}s",
            f"robots/nanites em obra ({ccd:.0f}s)",
        )
    return None


def _wait_for_resources(
    page, tid: int, cap_s: float, next_lvl: int | str
) -> tuple[float | None, str, str]:
    if "component=lfbuildings" not in page.url:
        open_component(page, "lfbuildings")
    cost = peek_tech_costs(page, tid)
    lab = f"LF#{tid}"
    if not cost:
        return None, "custo indisponível", f"quer {lab} → {next_lvl} mas custo indisponível"
    res = current_resources(page)
    have = {
        "metal": parse_ogame_int(res["metal"]),
        "crystal": parse_ogame_int(res["crystal"]),
        "deut": parse_ogame_int(res["deut"]),
    }
    prod = resource_production_per_hour(page)
    eta = secs_until_resources(cost, have, prod)
    if eta is None:
        return None, "sem ETA", (
            f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)})"
        )
    jitter = random.uniform(5, 20)
    raw = eta + jitter
    if raw > cap_s:
        return (
            cap_s,
            f"ETA {eta:.0f}s capado em {cap_s:.0f}s",
            f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; ETA {eta:.0f}s → cap)",
        )
    return (
        raw,
        f"ETA {eta:.0f}s +folga",
        f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)}; ETA {eta:.0f}s)",
    )


def mine_too_cheap(page, lf_cost: dict[str, int], techs=None) -> bool:
    """True if next classic mine costs less ConvertedDeut than LF upgrade."""
    if techs is None:
        open_component(page, "supplies")
        techs = parse_technologies(page)
    elif "component=supplies" not in (page.url or ""):
        open_component(page, "supplies")
    mines = [
        t
        for tid in (METAL, CRYSTAL, DEUT)
        if (t := techs.get(tid)) and t.status in ("on", "disabled")
    ]
    if not mines:
        return False
    mid = min(mines, key=lambda t: t.level).id
    mcost = peek_tech_costs(page, mid)
    if not mcost:
        return False
    return lf_beats_mine(lf_cost, mcost)


def lf_mine_celestial(
    page,
    celestial: Celestial,
    cfg: dict,
    interval_max_s: float,
    book=None,
    brain: dict | None = None,
    leave_slots: int = 1,
) -> tuple[str | None, float | None, str | None, str]:
    if celestial.coords.type == "Moon":
        return None, None, "lua", "skip lua"

    switch_celestial(page, celestial)

    # crystal gate
    open_component(page, "supplies")
    supplies = parse_technologies(page)
    crystal_lvl = supplies[CRYSTAL].level if CRYSTAL in supplies else 0
    need = int(cfg.get("StartFromCrystalMineLvl") or 0)
    if crystal_lvl < need:
        # ponytail: CheckInterval até automine subir cristal; baixar StartFromCrystalMineLvl p/ LF cedo
        why = f"CrystalMine {crystal_lvl}<{need}"
        return None, None, why, why

    open_component(page, "lfbuildings")
    if (busy := _busy_wait(page)) is not None:
        return busy

    techs = parse_technologies(page)
    pop = parse_population(page)
    energy = parse_ogame_int(current_resources(page).get("energy", "0"))
    has_lf = any(is_lf_building(t.id) and t.level >= 1 for t in techs.values())
    # prio food/pop may target level-0 slots when pop stats need them
    if not has_lf and pop is None:
        return None, None, "sem LF", "sem lifeform / prédios ≥1"

    prevent_tech = lf_research_queue(page)[0] != 0
    tid = pick_next(
        techs, cfg, prevent_tech=prevent_tech, pop=pop, energy=energy
    )
    if tid is None:
        want = pick_next(
            techs,
            cfg,
            afford=False,
            prevent_tech=prevent_tech,
            pop=pop,
            energy=energy,
        )
        if want is None:
            return None, None, "nada sob cap", "nada sob cap / affordável"
        nxt = techs[want].level + 1
        wait, sched, detail = _wait_for_resources(page, want, interval_max_s, nxt)
        brain = brain or {}
        slow = wait is None or wait >= interval_max_s
        if slow and transports_enabled(brain, cfg):
            if "component=lfbuildings" not in page.url:
                open_component(page, "lfbuildings")
            cost = peek_tech_costs(page, want) or {}
            if cost:
                tr, tags = send_bundled_transport(
                    page,
                    celestial,
                    brain,
                    cost,
                    seed_kind=KIND_LF_BUILD,
                    seed_tag=f"LF#{want}→{nxt}",
                    seed_tid=want,
                    leave_slots=leave_slots,
                )
                if tr.startswith("ok") or tr == "incoming":
                    twait, tsched = transport_retry_wait(page, celestial)
                    what = "+".join(tags) if tags else f"LF#{want}→{nxt}"
                    return (
                        f"transport LF#{want}",
                        twait,
                        tsched or f"transport → {what}",
                        f"transport {tr} p/ {what}",
                    )
                detail = f"{detail}; transport: {tr}"
        wait, arr = clamp_wait_to_incoming(page, celestial, wait)
        if arr:
            sched = arr
        return f"wait LF#{want}", wait, sched, detail

    cost = peek_tech_costs(page, tid) or {}
    if cfg.get("PreventIfMoreExpensiveThanNextMine") and cost:
        if mine_too_cheap(page, cost):
            open_component(page, "lfbuildings")
            return None, None, "mine first", (
                f"LF#{tid} mais caro que próxima mina — skip"
            )
        open_component(page, "lfbuildings")
        # re-open detail after supplies hop
        cost = peek_tech_costs(page, tid) or cost

    cur = techs[tid].level
    nxt = cur + 1
    fail = build_technology(page, tid)
    if fail:
        return (
            f"fail LF#{tid}",
            90.0,
            "retry 90s",
            f"click falhou LF#{tid} {cur}→{nxt} ({fail})",
        )
    if book is not None and cost:
        book.spend(celestial.id, cost)
    cd = lf_building_countdown(page)
    if cd > 0:
        wait = cd + random.uniform(5, 15)
        sched = f"countdown {cd:.0f}s"
    else:
        wait = random.uniform(20, 45)
        sched = "pós-build 20–45s"
    return (
        f"LF#{tid}→{nxt}",
        wait,
        sched,
        f"LF slot{slot_of(tid)} {cur}→{nxt} ({_fmt_cost(cost)})",
    )


class LifeformAutoMineWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        brain = settings.get("Brain") or {}
        cfg = brain.get("LifeformAutoMine") or {}
        if not brain.get("Active") or not cfg.get("Active"):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        exclude = cfg.get("Exclude") or []
        celestials = [c for c in parse_celestials(page) if c.coords.type == "Planet"]
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
            _log(f"lfmine: {why} — retry {wait_s:.0f}s", "warn")
            return "retry DOM"
        if not todo:
            wait_s = random.uniform(self.interval_min, self.interval_max)
            self._next_wait = wait_s
            self.reason = f"todos excluded (CheckInterval {lo_m:.0f}–{hi_m:.0f}min)"
            _log(f"lfmine: próxima decisão em {wait_s:.0f}s — {self.reason}")
            return "excluded"

        leave_slots = int(ctx.get("slots_to_leave_free") or 1)
        for c in todo:
            tag = c.label
            try:
                result, wait, why, line = lf_mine_celestial(
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
                _log(f"lfmine {tag}: erro UI ({err}) — retry 90s", "warn")
                waits.append((90.0, f"{tag}: erro UI"))
                continue
            lvl = "ok" if result and "→" in (result or "") else "info"
            if result and str(result).startswith("fail"):
                lvl = "warn"
            _log(f"lfmine {tag}: {line}", lvl)
            if (sw := schedule_why(wait, why, self.interval_min, self.interval_max)):
                waits.append((sw[0], f"{tag}: {sw[1]}"))
            if result:
                built.append(f"{tag} {result}")

        wait_s, why = pick_schedule(waits, self.interval_min, self.interval_max)
        self._next_wait = wait_s
        self.reason = why
        _log(f"lfmine: próxima decisão em {wait_s:.0f}s — {why}")
        return f"{len(built)} actions" if built else "nada"


if __name__ == "__main__":
    import subprocess
    import sys

    raise SystemExit(
        subprocess.call([sys.executable, "-m", "features.lifeform_automine_pick"])
    )
