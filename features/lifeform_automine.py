"""E06 Lifeform AutoMine: upgrade LF buildings already ≥1 under slot caps."""
from __future__ import annotations

import math
import random
from typing import Any

from game import (
    Celestial,
    Tech,
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
    parse_technologies,
    peek_tech_costs,
    resource_production_per_hour,
    secs_until_resources,
    switch_celestial,
)
from runtime import Worker, pick_schedule, schedule_why
from features.transports import send_miner_transport, transports_enabled

CRYSTAL = 2
ROBOTS, NANITES = 14, 15
METAL, DEUT = 1, 3

# slot → settings key (same for all races; id % 100 = slot 1..12)
SLOT_CAPS = {
    1: "MaxBasePopulationBuilding",
    2: "MaxBaseFoodBuilding",
    3: "MaxBaseTechBuilding",
    4: "MaxT2Building",
    5: "MaxT3Building",
    6: "MaxBuilding6",
    7: "MaxBuilding7",
    8: "MaxBuilding8",
    9: "MaxBuilding9",
    10: "MaxBuilding10",
    11: "MaxBuilding11",
    12: "MaxBuilding12",
}


def is_lf_building(tid: int) -> bool:
    slot = tid % 100
    return 1 <= slot <= 12 and tid // 100 in (111, 121, 131, 141)


def slot_of(tid: int) -> int:
    return tid % 100


def under_cap(tid: int, level: int, cfg: dict) -> bool:
    key = SLOT_CAPS.get(slot_of(tid))
    if not key:
        return False
    return level < int(cfg.get(key) or 0)


def converted_deut(cost: dict[str, int]) -> int:
    return int(
        math.ceil(
            cost.get("metal", 0) / 2.5
            + cost.get("crystal", 0) / 1.5
            + cost.get("deut", 0)
        )
    )


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
    prevent_tech: bool = False,
) -> int | None:
    """Cheapest-by-level among LF buildings already ≥1 under cap."""

    def ok(t: Tech) -> bool:
        if not is_lf_building(t.id) or t.level < 1 or not under_cap(t.id, t.level, cfg):
            return False
        if prevent_tech and slot_of(t.id) == 3:
            return False
        if afford:
            return t.status == "on"
        return t.status in ("on", "disabled")

    cands = [t for t in techs.values() if ok(t)]
    if not cands:
        return None
    # ponytail: level asc instead of ConvertedDeuterium; peek-all when ROI matters
    return min(cands, key=lambda t: (t.level, slot_of(t.id))).id


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


def _mine_too_cheap(page, lf_cost: dict[str, int]) -> bool:
    """True if next classic mine costs less ConvertedDeut than LF upgrade."""
    open_component(page, "supplies")
    techs = parse_technologies(page)
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
    return converted_deut(lf_cost) > converted_deut(mcost)


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
    if not any(is_lf_building(t.id) and t.level >= 1 for t in techs.values()):
        return None, None, "sem LF", "sem lifeform / prédios ≥1"

    prevent_tech = lf_research_queue(page)[0] != 0
    tid = pick_next(techs, cfg, prevent_tech=prevent_tech)
    if tid is None:
        want = pick_next(techs, cfg, afford=False, prevent_tech=prevent_tech)
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
                tr = send_miner_transport(
                    page, brain, celestial, cost, leave_slots=leave_slots
                )
                if tr.startswith("ok"):
                    return (
                        f"transport LF#{want}",
                        random.uniform(60, 120),
                        f"transport → LF#{want}→{nxt}",
                        f"transport {tr} p/ LF#{want}→{nxt}",
                    )
                detail = f"{detail}; transport: {tr}"
        return f"wait LF#{want}", wait, sched, detail

    cost = peek_tech_costs(page, tid) or {}
    if cfg.get("PreventIfMoreExpensiveThanNextMine") and cost:
        if _mine_too_cheap(page, cost):
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
        todo = [c for c in celestials if not _excluded(c, exclude)]
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
    cfg = {
        "MaxBasePopulationBuilding": 60,
        "MaxBaseFoodBuilding": 62,
        "MaxBaseTechBuilding": 6,
        "MaxT2Building": 10,
        "MaxT3Building": 8,
        "MaxBuilding6": 5,
        "MaxBuilding7": 5,
        "MaxBuilding8": 5,
        "MaxBuilding9": 5,
        "MaxBuilding10": 5,
        "MaxBuilding11": 5,
        "MaxBuilding12": 5,
    }
    techs = {
        11101: Tech(11101, 10, "on"),
        11102: Tech(11102, 8, "on"),
        11103: Tech(11103, 2, "disabled"),
        11106: Tech(11106, 0, "on"),  # level 0 → skip
    }
    assert pick_next(techs, cfg) == 11102  # lower level among ≥1 on
    assert pick_next(techs, cfg, afford=False) == 11103
    assert pick_next(techs, cfg, prevent_tech=True, afford=False) == 11102
    assert under_cap(11101, 59, cfg)
    assert not under_cap(11101, 60, cfg)
    assert converted_deut({"metal": 250, "crystal": 150, "deut": 10}) == 210
    assert is_lf_building(11101) and not is_lf_building(1)
    print("lifeform_automine ok")
