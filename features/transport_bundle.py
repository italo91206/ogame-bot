"""E04-T05: somar custos das filas paralelas idle (+ research se Target=dest)."""
from __future__ import annotations

import filelog
from game import (
    Celestial,
    building_queue,
    open_component,
    parse_technologies,
    resource_storage,
)

KIND_CLASSIC = "classic"
KIND_RESEARCH = "research"
KIND_LF_BUILD = "lf_build"
KIND_LF_TECH = "lf_tech"

# TB-02: se Origin stock < soma, financiar nesta ordem (all-or-nothing nos peeks).
_PRIORITY = {
    KIND_CLASSIC: 0,
    KIND_RESEARCH: 1,
    KIND_LF_TECH: 2,
    KIND_LF_BUILD: 3,
}

BundlePart = tuple[str, dict[str, int], str]  # kind, cost, tag


def note_reason(reasons: list[str] | None, msg: str) -> None:
    if reasons is not None:
        reasons.append(msg)


def emit_bundle_decision(
    celestial: Celestial, tags: list[str], reasons: list[str], status: str
) -> None:
    """File-only: decisão do bundle (TUI fica na linha compacta do worker)."""
    c = celestial.coords
    where = f"{c.galaxy}:{c.system}:{c.position}"
    if c.type == "Moon":
        where += "M"
    keep = "+".join(tags) if tags else "-"
    # send= already in reasons via send_miner_transport; keep status as fallback
    why = list(reasons)
    if not any(r.startswith("send=") for r in why):
        why.append(f"send={status}")
    body = "; ".join(why) if why else f"send={status}"
    filelog.write(f"bundle {where} keep={keep}; {body}", "detail")


class CelTechCache:
    """TB-C7: parse each UI component once per transport tick on a celestial."""

    __slots__ = ("page", "_by")

    def __init__(self, page):
        self.page = page
        self._by: dict[str, dict] = {}

    def techs(self, component: str) -> dict:
        if component not in self._by:
            open_component(self.page, component)
            self._by[component] = parse_technologies(self.page)
        elif f"component={component}" not in (self.page.url or ""):
            open_component(self.page, component)
        return self._by[component]


def sum_costs(*costs: dict[str, int] | None) -> dict[str, int]:
    out = {"metal": 0, "crystal": 0, "deut": 0}
    for c in costs:
        if not c:
            continue
        for k in out:
            out[k] += int(c.get(k) or 0)
    return out


def clamp_cost_to_storage(
    cost: dict[str, int],
    storage: dict[str, int],
    reasons: list[str] | None = None,
) -> dict[str, int]:
    """Cap each resource at dest warehouse; skip clamp if storage unknown (0)."""
    out = {"metal": 0, "crystal": 0, "deut": 0}
    cuts: list[str] = []
    for k in out:
        c = int(cost.get(k) or 0)
        s = int(storage.get(k) or 0)
        out[k] = min(c, s) if s > 0 else c
        if s > 0 and c > s:
            cuts.append(f"{k[0].upper()}{c}→{s}")
    if cuts:
        note_reason(reasons, "clamp " + ",".join(cuts))
    return out


def fit_parts_to_origin(
    parts: list[BundlePart],
    dest_have: dict[str, int],
    origin_have: dict[str, int],
    reasons: list[str] | None = None,
) -> tuple[dict[str, int], list[str]]:
    """Keep slots by priority while Origin can fully fund the cumulative missing.

    First (highest prio) always kept — partial send ok. Later slots all-or-nothing
    against Origin stock so LF build does not drain a poor Origin.
    """
    from features.transports import missing_resources

    if not parts:
        return {"metal": 0, "crystal": 0, "deut": 0}, []
    ordered = sorted(parts, key=lambda p: _PRIORITY.get(p[0], 99))
    origin = {k: int(origin_have.get(k) or 0) for k in ("metal", "crystal", "deut")}
    kept: list[BundlePart] = []
    dropped: list[str] = []
    for kind, cost, tag in ordered:
        trial = sum_costs(*(c for _, c, _ in kept), cost)
        need = missing_resources(trial, dest_have)
        if not kept:
            kept.append((kind, cost, tag))
            need0 = missing_resources(cost, dest_have)
            if any(origin[k] < need0[k] for k in origin):
                note_reason(reasons, f"partial {tag}=origin")
            continue
        if all(origin[k] >= need[k] for k in origin):
            kept.append((kind, cost, tag))
        else:
            dropped.append(tag)
    if dropped:
        note_reason(reasons, "drop " + "+".join(dropped) + "=origin")
    return sum_costs(*(c for _, c, _ in kept)), [t for _, _, t in kept]


def bundle_parallel_cost(
    page,
    celestial: Celestial,
    brain: dict,
    *,
    seed: dict[str, int] | None = None,
    seed_kind: str = KIND_CLASSIC,
    seed_tag: str = "",
    seed_tid: int | None = None,
    reasons: list[str] | None = None,
) -> tuple[dict[str, int], list[str], list[BundlePart]]:
    """Best-effort N∈{1..4}: seed + other idle parallel slots.

    Returns (clamped_sum, tags, parts). Pass `parts` to send_miner_transport for TB-02.
    """
    from features.automine_pick import ROBOTS, NANITES
    from features.transport_bundle_peek import (
        classic_next,
        lf_build_next,
        lf_tech_next,
        research_next,
    )

    moon = celestial.coords.type == "Moon"
    cache = CelTechCache(page)
    parts: list[BundlePart] = []
    classic_tid = seed_tid if seed_kind == KIND_CLASSIC else None
    lf_build_tid = seed_tid if seed_kind == KIND_LF_BUILD else None
    lf_tech_tid = seed_tid if seed_kind == KIND_LF_TECH else None
    classic_busy = building_queue(page)[0]

    if seed and sum(int(seed.get(k) or 0) for k in ("metal", "crystal", "deut")) > 0:
        tag = seed_tag or seed_kind
        parts.append((seed_kind, seed, tag))
        note_reason(reasons, f"seed={seed_kind} {tag}")

    if seed_kind != KIND_CLASSIC:
        hit = classic_next(page, brain, moon, cache, reasons)
        if hit:
            tid, cost, tag = hit
            classic_tid = tid
            parts.append((KIND_CLASSIC, cost, tag))

    if moon:
        note_reason(reasons, "moon=só classic")
        total = sum_costs(*(c for _, c, _ in parts))
        tags = [t for _, _, t in parts]
        # clamp reason só no send (pós-fit Origin)
        return clamp_cost_to_storage(total, resource_storage(page)), tags, parts

    from features.transport_lookahead import apply_classic_lookahead

    parts, classic_tids = apply_classic_lookahead(
        page, brain, celestial, parts, classic_tid, cache=cache, reasons=reasons
    )
    block_lf = classic_busy in (ROBOTS, NANITES) or bool(
        classic_tids & {ROBOTS, NANITES}
    )

    if seed_kind != KIND_RESEARCH:
        hit = research_next(page, brain, celestial, cache, reasons)
        if hit:
            cost, tag = hit
            parts.append((KIND_RESEARCH, cost, tag))

    if seed_kind != KIND_LF_TECH:
        hit = lf_tech_next(page, brain, cache, reasons)
        if hit:
            tid, cost, tag = hit
            lf_tech_tid = tid
            parts.append((KIND_LF_TECH, cost, tag))

    if seed_kind != KIND_LF_BUILD:
        hit = lf_build_next(page, brain, block_lf=block_lf, cache=cache, reasons=reasons)
        if hit:
            tid, cost, tag = hit
            lf_build_tid = tid
            parts.append((KIND_LF_BUILD, cost, tag))

    from features.transport_lookahead_lf import (
        apply_lf_build_lookahead,
        apply_lf_tech_lookahead,
    )

    parts = apply_lf_tech_lookahead(
        page, brain, celestial, parts, lf_tech_tid, cache=cache, reasons=reasons
    )
    parts = apply_lf_build_lookahead(
        page, brain, celestial, parts, lf_build_tid, cache=cache, reasons=reasons
    )

    total = sum_costs(*(c for _, c, _ in parts))
    tags = [t for _, _, t in parts]
    return clamp_cost_to_storage(total, resource_storage(page)), tags, parts


def send_bundled_transport(
    page,
    celestial: Celestial,
    brain: dict,
    seed: dict[str, int],
    *,
    seed_kind: str,
    seed_tag: str,
    seed_tid: int | None = None,
    leave_slots: int = 1,
) -> tuple[str, list[str]]:
    """TB-C8: bundle_parallel_cost + send_miner_transport.

    Returns (status from send_miner_transport, tags after Origin fit).
    Emite decisão file-only (`detail`) com reasons de omit/drop/clamp/stack/send.
    """
    from features.transports import send_miner_transport

    reasons: list[str] = []
    bundled, tags, parts = bundle_parallel_cost(
        page,
        celestial,
        brain,
        seed=seed,
        seed_kind=seed_kind,
        seed_tag=seed_tag,
        seed_tid=seed_tid,
        reasons=reasons,
    )
    tr = send_miner_transport(
        page,
        brain,
        celestial,
        bundled,
        leave_slots=leave_slots,
        parts=parts,
        out_tags=tags,
        reasons=reasons,
    )
    emit_bundle_decision(celestial, tags, reasons, tr)
    return tr, tags


if __name__ == "__main__":
    # TB-C7: cache hits skip re-parse (patch this module's globals)
    class _P:
        url = "component=supplies"

    opens: list[str] = []
    g = globals()
    _real_open, _real_parse = g["open_component"], g["parse_technologies"]

    def _open(page, comp):
        opens.append(comp)
        page.url = f"component={comp}"

    def _parse(_page):
        return {1: "t"}

    g["open_component"], g["parse_technologies"] = _open, _parse
    try:
        p = _P()
        c = CelTechCache(p)
        assert c.techs("supplies") == {1: "t"} and opens == ["supplies"]
        p.url = "component=facilities"
        assert c.techs("supplies") == {1: "t"} and opens == ["supplies", "supplies"]
        assert c.techs("supplies") == {1: "t"} and opens == ["supplies", "supplies"]
    finally:
        g["open_component"], g["parse_technologies"] = _real_open, _real_parse

    assert sum_costs(
        {"metal": 100, "crystal": 0, "deut": 10},
        {"metal": 50, "crystal": 20, "deut": 0},
    ) == {"metal": 150, "crystal": 20, "deut": 10}
    assert sum_costs({}, None) == {"metal": 0, "crystal": 0, "deut": 0}
    assert sum_costs() == {"metal": 0, "crystal": 0, "deut": 0}

    rs: list[str] = []
    assert clamp_cost_to_storage(
        {"metal": 15_000, "crystal": 100, "deut": 50},
        {"metal": 10_000, "crystal": 5_000, "deut": 0},
        rs,
    ) == {"metal": 10_000, "crystal": 100, "deut": 50}
    assert any(x.startswith("clamp ") for x in rs)
    assert clamp_cost_to_storage(
        {"metal": 100, "crystal": 0, "deut": 0},
        {"metal": 0, "crystal": 0, "deut": 0},
    ) == {"metal": 100, "crystal": 0, "deut": 0}

    dest0 = {"metal": 0, "crystal": 0, "deut": 0}
    classic = (KIND_CLASSIC, {"metal": 100, "crystal": 0, "deut": 0}, "Metal→1")
    research = (KIND_RESEARCH, {"metal": 100, "crystal": 0, "deut": 0}, "Energy→1")
    lf_tech = (KIND_LF_TECH, {"metal": 100, "crystal": 0, "deut": 0}, "LFtech#1")
    lf_build = (KIND_LF_BUILD, {"metal": 100, "crystal": 0, "deut": 0}, "LF#1")
    rs = []
    cost, tags = fit_parts_to_origin(
        [lf_build, classic, lf_tech, research],
        dest0,
        {"metal": 200, "crystal": 0, "deut": 0},
        rs,
    )
    assert cost == {"metal": 200, "crystal": 0, "deut": 0}
    assert tags == ["Metal→1", "Energy→1"]
    assert any("drop " in x and "origin" in x for x in rs)
    cost, tags = fit_parts_to_origin(
        [lf_build, classic, lf_tech, research],
        dest0,
        {"metal": 500, "crystal": 0, "deut": 0},
    )
    assert cost["metal"] == 400 and tags == [
        "Metal→1",
        "Energy→1",
        "LFtech#1",
        "LF#1",
    ]
    rs = []
    cost, tags = fit_parts_to_origin(
        [lf_build, classic], dest0, {"metal": 40, "crystal": 0, "deut": 0}, rs
    )
    assert cost == {"metal": 100, "crystal": 0, "deut": 0} and tags == ["Metal→1"]
    assert any("partial " in x for x in rs)
    cost, tags = fit_parts_to_origin(
        [classic, lf_tech],
        {"metal": 50, "crystal": 0, "deut": 0},
        {"metal": 100, "crystal": 0, "deut": 0},
    )
    assert cost == {"metal": 100, "crystal": 0, "deut": 0} and tags == ["Metal→1"]

    from features.transport_bundle_peek import dest_is_ar_target

    class _C:
        pass

    cel = _C()
    cel.coords = _C()
    cel.coords.galaxy, cel.coords.system, cel.coords.position = 1, 2, 3
    cel.coords.type = "Planet"
    assert dest_is_ar_target(cel, {"Target": {"Galaxy": 1, "System": 2, "Position": 3}})
    assert not dest_is_ar_target(cel, {"Target": {}})
    assert not dest_is_ar_target(
        cel, {"Target": {"Galaxy": 1, "System": 2, "Position": 9}}
    )
    from features.lifeform_automine_pick import lf_beats_mine

    cheap_mine = {"metal": 100, "crystal": 50, "deut": 0}
    pricey_lf = {"metal": 5_000, "crystal": 2_000, "deut": 500}
    assert lf_beats_mine(pricey_lf, cheap_mine)
    assert not lf_beats_mine(cheap_mine, pricey_lf)

    _real_b = g["bundle_parallel_cost"]

    def _fake_b(_page, _cel, _brain, *, seed, seed_kind, seed_tag, seed_tid=None, reasons=None):
        assert seed == {"metal": 10} and seed_kind == KIND_CLASSIC and seed_tag == "X"
        note_reason(reasons, "seed=classic X")
        return {"metal": 10}, ["X"], [(KIND_CLASSIC, {"metal": 10}, "X")]

    g["bundle_parallel_cost"] = _fake_b
    import features.transports as _tr

    _real_s = _tr.send_miner_transport
    emitted: list[str] = []
    _real_emit = g["emit_bundle_decision"]

    def _fake_emit(celestial, tags, reasons, status):
        emitted.append(f"{tags}|{';'.join(reasons)}|{status}")

    def _fake_s(_page, _brain, _dest, cost, *, leave_slots=1, parts=None, out_tags=None, reasons=None):
        assert cost == {"metal": 10} and parts and out_tags is not None
        out_tags[:] = ["X"]
        note_reason(reasons, "send=ok")
        return "ok"

    g["emit_bundle_decision"] = _fake_emit
    _tr.send_miner_transport = _fake_s
    try:
        tr, tags = send_bundled_transport(
            None, cel, {}, {"metal": 10}, seed_kind=KIND_CLASSIC, seed_tag="X"
        )
        assert tr == "ok" and tags == ["X"]
        assert emitted and "seed=classic X" in emitted[0] and "send=ok" in emitted[0]
    finally:
        g["bundle_parallel_cost"] = _real_b
        g["emit_bundle_decision"] = _real_emit
        _tr.send_miner_transport = _real_s

    rs = []
    note_reason(rs, "a")
    note_reason(None, "b")
    assert rs == ["a"]
    print("transport_bundle ok")
