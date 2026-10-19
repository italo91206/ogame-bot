"""E07 Lifeform AutoResearch: upgrade LF techs already ≥1 under MaxTechs caps."""
from __future__ import annotations

import random
from typing import Any

from game import (
    Celestial,
    Tech,
    build_technology,
    current_resources,
    lf_research_countdown,
    lf_research_queue,
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
from runtime import Worker, pick_schedule, schedule_why
from features.transports import (
    clamp_wait_to_incoming,
    send_miner_transport,
    transport_retry_wait,
    transports_enabled,
)


def is_lf_tech(tid: int) -> bool:
    slot = tid % 100
    return 1 <= slot <= 18 and tid // 100 in (112, 122, 132, 142)


def tech_cap_key(tid: int) -> str:
    """Slot 1..18 → MaxTechs11..16 / 21..26 / 31..36."""
    slot = tid % 100
    if slot <= 6:
        return f"MaxTechs1{slot}"
    if slot <= 12:
        return f"MaxTechs2{slot - 6}"
    return f"MaxTechs3{slot - 12}"


def under_cap(tid: int, level: int, cfg: dict) -> bool:
    key = tech_cap_key(tid)
    default = int(cfg.get("MaxResearchLevel") or 0)
    return level < int(cfg.get(key, default) or 0)


def _excluded(c: Celestial, exclude: list) -> bool:
    for e in exclude or []:
        if (
            int(e.get("Galaxy", -1)) == c.coords.galaxy
            and int(e.get("System", -1)) == c.coords.system
            and int(e.get("Position", -1)) == c.coords.position
            and (e.get("Type") or "Planet") == c.coords.type
        ):
            return True
    return False


def pick_next(
    techs: dict[int, Tech],
    cfg: dict,
    *,
    afford: bool = True,
) -> int | None:
    """Among LF techs level ≥1 under cap; prefer lowest level."""

    def ok(t: Tech) -> bool:
        if not is_lf_tech(t.id) or t.level < 1 or not under_cap(t.id, t.level, cfg):
            return False
        if afford:
            return t.status == "on"
        return t.status in ("on", "disabled")

    cands = [t for t in techs.values() if ok(t)]
    if not cands:
        return None
    # ponytail: level asc instead of peek-all cheaper swap; add when needed
    return min(cands, key=lambda t: (t.level, t.id)).id


_fmt_cost = format_cost


def _busy_wait(page) -> tuple[str | None, float | None, str | None, str] | None:
    rid, cd = lf_research_queue(page)
    if not rid:
        return None
    wait = cd + random.uniform(5, 15) if cd > 0 else random.uniform(5, 20)
    why = f"LF research {cd:.0f}s" if cd > 0 else "LF research ~0s"
    return "busy", wait, why, f"fila LF research ocupada ({cd:.0f}s)"


def _wait_for_resources(
    page, tid: int, cap_s: float, next_lvl: int | str
) -> tuple[float | None, str, str]:
    if "component=lfresearch" not in page.url:
        open_component(page, "lfresearch")
    cost = peek_tech_costs(page, tid)
    lab = f"LFtech#{tid}"
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
        return None, "sem ETA", f"sem recurso p/ {lab} → {next_lvl} ({_fmt_cost(cost)})"
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


def lf_research_celestial(
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
    open_component(page, "lfresearch")
    if (busy := _busy_wait(page)) is not None:
        return busy

    techs = parse_technologies(page)
    if not any(is_lf_tech(t.id) and t.level >= 1 for t in techs.values()):
        return None, None, "sem LF tech", "sem techs LF ≥1"

    tid = pick_next(techs, cfg)
    if tid is None:
        want = pick_next(techs, cfg, afford=False)
        if want is None:
            return None, None, "nada sob cap", "nada sob cap / affordável"
        nxt = techs[want].level + 1
        wait, sched, detail = _wait_for_resources(page, want, interval_max_s, nxt)
        brain = brain or {}
        slow = wait is None or wait >= interval_max_s
        if slow and transports_enabled(brain, cfg):
            cost = peek_tech_costs(page, want) or {}
            if cost:
                tr = send_miner_transport(
                    page, brain, celestial, cost, leave_slots=leave_slots
                )
                if tr.startswith("ok") or tr == "incoming":
                    twait, tsched = transport_retry_wait(page, celestial)
                    return (
                        f"transport LFtech#{want}",
                        twait,
                        tsched or f"transport → LFtech#{want}→{nxt}",
                        f"transport {tr} p/ LFtech#{want}→{nxt}",
                    )
                detail = f"{detail}; transport: {tr}"
        wait, arr = clamp_wait_to_incoming(page, celestial, wait)
        if arr:
            sched = arr
        return f"wait LFtech#{want}", wait, sched, detail

    cost = peek_tech_costs(page, tid) or {}
    cur = techs[tid].level
    nxt = cur + 1
    fail = build_technology(page, tid)
    if fail:
        return (
            f"fail LFtech#{tid}",
            90.0,
            "retry 90s",
            f"click falhou LFtech#{tid} {cur}→{nxt} ({fail})",
        )
    if book is not None and cost:
        book.spend(celestial.id, cost)
    cd = lf_research_countdown(page)
    if cd > 0:
        wait = cd + random.uniform(5, 15)
        sched = f"countdown {cd:.0f}s"
    else:
        wait = random.uniform(20, 45)
        sched = "pós-research 20–45s"
    return (
        f"LFtech#{tid}→{nxt}",
        wait,
        sched,
        f"LFtech {tech_cap_key(tid)} {cur}→{nxt} ({_fmt_cost(cost)})",
    )


class LifeformAutoResearchWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        brain = settings.get("Brain") or {}
        cfg = brain.get("LifeformAutoResearch") or {}
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
        todo = [c for c in celestials if not _excluded(c, exclude)]
        if not celestials:
            wait_s, why = pick_schedule([], self.interval_min, self.interval_max)
            self._next_wait = wait_s
            self.reason = why
            _log(f"lfresearch: {why} — retry {wait_s:.0f}s", "warn")
            return "retry DOM"
        if not todo:
            wait_s = random.uniform(self.interval_min, self.interval_max)
            self._next_wait = wait_s
            self.reason = f"todos excluded (CheckInterval {lo_m:.0f}–{hi_m:.0f}min)"
            _log(f"lfresearch: próxima decisão em {wait_s:.0f}s — {self.reason}")
            return "excluded"

        leave_slots = int(ctx.get("slots_to_leave_free") or 1)
        for c in todo:
            tag = c.label
            try:
                result, wait, why, line = lf_research_celestial(
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
                _log(f"lfresearch {tag}: erro UI ({err}) — retry 90s", "warn")
                waits.append((90.0, f"{tag}: erro UI"))
                continue
            lvl = "ok" if result and "→" in (result or "") else "info"
            if result and str(result).startswith("fail"):
                lvl = "warn"
            _log(f"lfresearch {tag}: {line}", lvl)
            if (sw := schedule_why(wait, why, self.interval_min, self.interval_max)):
                waits.append((sw[0], f"{tag}: {sw[1]}"))
            if result:
                built.append(f"{tag} {result}")

        wait_s, why = pick_schedule(waits, self.interval_min, self.interval_max)
        self._next_wait = wait_s
        self.reason = why
        _log(f"lfresearch: próxima decisão em {wait_s:.0f}s — {why}")
        return f"{len(built)} actions" if built else "nada"


if __name__ == "__main__":
    cfg = {"MaxResearchLevel": 6, "MaxTechs11": 8, "MaxTechs12": 4}
    techs = {
        11201: Tech(11201, 5, "on"),
        11202: Tech(11202, 2, "on"),
        11203: Tech(11203, 1, "disabled"),
        11207: Tech(11207, 0, "on"),
    }
    assert tech_cap_key(11201) == "MaxTechs11"
    assert tech_cap_key(11207) == "MaxTechs21"
    assert tech_cap_key(11218) == "MaxTechs36"
    assert pick_next(techs, cfg) == 11202
    assert not under_cap(11202, 4, cfg)  # MaxTechs12=4 → level 4 capped
    assert pick_next(
        {11201: Tech(11201, 5, "on"), 11203: Tech(11203, 1, "disabled")},
        cfg,
        afford=False,
    ) == 11203
    assert is_lf_tech(13205) and not is_lf_tech(11101)
    print("lifeform_autoresearch ok")
