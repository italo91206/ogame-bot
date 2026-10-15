"""E12-T01 AutoFarm: scan inactive systems + send spy probes."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from game import parse_celestials, parse_slots, switch_celestial
from game.fleet import MISSION_SPY, parse_ships, send_fleet
from game.galaxy import fetch_galaxy, ogame_distance
from game.models import Celestial, Coords
from runtime import Worker, slots_available

PROBE_ID = 210
STATE_PENDING = "pending"
STATE_PROBED = "probes_sent"

# fallbacks quando chave ausente / ScanRange vazio (espelha TBot instance_settings)
_DEFAULTS = {
    "Active": True,
    "KeepReportFor": 180,
    "NumProbes": 10,
    "TargetsProbedBeforeAttack": 30,
    "SlotsToLeaveFree": 1,
    "CheckIntervalMin": 30,
    "CheckIntervalMax": 60,
    "ScanRadius": 30,  # sistemas ± home se ScanRange=[]
}


def _cfg(cfg: dict, key: str) -> Any:
    if key in cfg and cfg[key] is not None:
        return cfg[key]
    return _DEFAULTS[key]


def default_scan_range(celestials: list[Celestial], radius: int = 30) -> list[dict]:
    """Um range por galáxia das colônias: system±radius (clamp ≥1)."""
    by_g: dict[int, list[int]] = {}
    for c in celestials:
        by_g.setdefault(c.coords.galaxy, []).append(c.coords.system)
    out: list[dict] = []
    r = max(0, int(radius))
    for g, systems in sorted(by_g.items()):
        mid = sorted(systems)[len(systems) // 2]
        out.append(
            {
                "Galaxy": g,
                "StartSystem": max(1, mid - r),
                "EndSystem": mid + r,
            }
        )
    return out


@dataclass
class FarmTarget:
    coords: Coords
    state: str = STATE_PENDING
    probed_at: float | None = None


def _key(c: Coords) -> str:
    return f"{c.galaxy}:{c.system}:{c.position}:{c.type}"


def flatten_scan_range(ranges: list) -> list[tuple[int, int]]:
    """ScanRange[] → [(galaxy, system), ...] inclusive."""
    out: list[tuple[int, int]] = []
    for r in ranges or []:
        g = int(r.get("Galaxy") or 0)
        a = int(r.get("StartSystem") or 0)
        b = int(r.get("EndSystem") or a)
        if g <= 0 or a <= 0 or b <= 0:
            continue
        if b < a:
            a, b = b, a
        for s in range(a, b + 1):
            out.append((g, s))
    return out


def is_excluded(coords: Coords, excludes: list) -> bool:
    for e in excludes or []:
        if int(e.get("Galaxy") or -1) != coords.galaxy:
            continue
        if int(e.get("System") or -1) != coords.system:
            continue
        pos = e.get("Position", e.get("Planet"))
        if pos is None or pos == "":
            return True
        if int(pos) == coords.position:
            return True
    return False


def system_excluded(galaxy: int, system: int, excludes: list) -> bool:
    return is_excluded(Coords(galaxy, system, 0), [
        e for e in (excludes or [])
        if e.get("Position", e.get("Planet")) in (None, "")
    ])


def _origin_match(c: Celestial, origins: list) -> bool:
    if not origins:
        return True
    for o in origins:
        if (
            int(o.get("Galaxy", -1)) == c.coords.galaxy
            and int(o.get("System", -1)) == c.coords.system
            and int(o.get("Position", -1)) == c.coords.position
            and (o.get("Type") or "Planet") == c.coords.type
        ):
            return True
    return False


def pick_spy_origin(
    origins: list[Celestial], target: Coords, probe_stock: dict[str, int], need: int
) -> Celestial | None:
    """Closest origin (moon first) with enough probes."""
    ranked = sorted(
        origins,
        key=lambda c: (
            0 if c.coords.type == "Moon" else 1,
            ogame_distance(c.coords, target),
        ),
    )
    for o in ranked:
        if probe_stock.get(o.id, 0) >= need:
            return o
    return None


def prune_targets(
    targets: dict[str, FarmTarget], keep_minutes: float, now: float | None = None
) -> None:
    """Re-probe AttackSent/old reports: here only age out probes_sent."""
    now = now if now is not None else time.time()
    ttl = max(0.0, float(keep_minutes)) * 60.0
    for t in list(targets.values()):
        if t.state != STATE_PROBED or t.probed_at is None:
            continue
        if ttl <= 0 or (now - t.probed_at) >= ttl:
            t.state = STATE_PENDING
            t.probed_at = None


class AutoFarmWorker(Worker):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._targets: dict[str, FarmTarget] = {}
        self._scan_i: int = 0
        self._probe_stock: dict[str, int] = {}

    def tick(self, ctx: dict[str, Any]) -> str:
        settings = ctx["settings"]
        cfg = settings.get("AutoFarm") or {}
        if not bool(_cfg(cfg, "Active")):
            self.active = False
            self.reason = "off"
            return "off"

        page = ctx["page"]
        leave = int(_cfg(cfg, "SlotsToLeaveFree") or ctx.get("slots_to_leave_free") or 1)
        tui = ctx.get("tui")
        refresh = ctx.get("refresh")

        def _log(msg: str, level: str = "info") -> None:
            if tui:
                tui.log(msg, level)
            if refresh:
                refresh()

        keep_min = float(_cfg(cfg, "KeepReportFor"))
        prune_targets(self._targets, keep_min)

        slots = parse_slots(page)
        if not slots_available(slots, leave):
            self._next_wait = random.uniform(30, 90)
            self.reason = f"slots {slots.free}/{slots.total}"
            return self.reason

        celestials = parse_celestials(page)
        scan_cfg = cfg.get("ScanRange") or []
        if not scan_cfg:
            scan_cfg = default_scan_range(celestials, int(_cfg(cfg, "ScanRadius")))
        systems = flatten_scan_range(scan_cfg)
        if not systems:
            self._next_wait = random.uniform(60, 180)
            self.reason = "ScanRange vazio"
            _log("farm: ScanRange vazio", "warn")
            return self.reason

        num_probes = max(1, int(_cfg(cfg, "NumProbes")))
        max_probe = max(1, int(_cfg(cfg, "TargetsProbedBeforeAttack")))
        excludes = cfg.get("Exclude") or []
        origins_cfg = cfg.get("Origin") or []

        origins = [c for c in celestials if _origin_match(c, origins_cfg)] or list(celestials)
        if not origins:
            self._next_wait = random.uniform(30, 90)
            self.reason = "sem origin"
            return self.reason

        # refresh probe counts on origins (lazy: once / tick)
        self._probe_stock = {}
        for o in origins:
            switch_celestial(page, o)
            ships = parse_ships(page)
            self._probe_stock[o.id] = int(ships.get(PROBE_ID, {}).get("number") or 0)

        probed = 0
        scanned = 0
        nsys = len(systems)
        start_i = self._scan_i % nsys

        for step in range(nsys):
            if probed >= max_probe:
                break
            if not slots_available(parse_slots(page), leave):
                break
            gi = (start_i + step) % nsys
            g, s = systems[gi]
            self._scan_i = (gi + 1) % nsys
            if system_excluded(g, s, excludes):
                continue

            try:
                found = fetch_galaxy(page, g, s)
            except Exception as e:
                _log(f"farm: galaxy {g}:{s} fail {e}", "warn")
                continue
            scanned += 1
            time.sleep(random.uniform(0.4, 1.2))

            for gt in found:
                if probed >= max_probe:
                    break
                if is_excluded(gt.coords, excludes):
                    continue
                ft = self._targets.get(_key(gt.coords))
                if ft is None:
                    ft = FarmTarget(coords=gt.coords)
                    self._targets[_key(gt.coords)] = ft
                if ft.state == STATE_PROBED:
                    continue

                origin = pick_spy_origin(origins, gt.coords, self._probe_stock, num_probes)
                if origin is None:
                    self._next_wait = random.uniform(60, 180)
                    self.reason = f"sem probes (≥{num_probes})"
                    _log(f"farm: sem probes nos origins (need {num_probes})", "warn")
                    return self.reason

                switch_celestial(page, origin)
                if not slots_available(parse_slots(page), leave):
                    break
                status = send_fleet(
                    page,
                    {PROBE_ID: num_probes},
                    gt.coords.galaxy,
                    gt.coords.system,
                    gt.coords.position,
                    mission=MISSION_SPY,
                    speed=10,
                    dest_type=1,
                )
                if status == "ok":
                    ft.state = STATE_PROBED
                    ft.probed_at = time.time()
                    self._probe_stock[origin.id] = max(
                        0, self._probe_stock.get(origin.id, 0) - num_probes
                    )
                    probed += 1
                    _log(
                        f"farm: spy {num_probes}p {origin.label} → {gt.coords}",
                        "ok",
                    )
                    time.sleep(random.uniform(1.0, 3.0))
                else:
                    _log(f"farm: spy {gt.coords} {status}", "warn")
                    self._next_wait = random.uniform(20, 60)
                    self.reason = status
                    return status

        lo = float(_cfg(cfg, "CheckIntervalMin")) * 60
        hi = float(_cfg(cfg, "CheckIntervalMax")) * 60
        self._next_wait = random.uniform(lo, max(lo, hi))
        self.reason = f"spy {probed}/{max_probe} scan {scanned} sys"
        _log(f"farm: {self.reason}", "info")
        return self.reason


if __name__ == "__main__":
    systems = flatten_scan_range(
        [{"Galaxy": 1, "StartSystem": 3, "EndSystem": 5}]
    )
    assert systems == [(1, 3), (1, 4), (1, 5)]
    assert is_excluded(Coords(1, 3, 4), [{"Galaxy": 1, "System": 3}])
    assert is_excluded(Coords(1, 3, 4), [{"Galaxy": 1, "System": 3, "Planet": 4}])
    assert not is_excluded(Coords(1, 3, 5), [{"Galaxy": 1, "System": 3, "Planet": 4}])
    o1 = Celestial("a", "A", Coords(1, 1, 1, "Planet"))
    o2 = Celestial("b", "B", Coords(1, 10, 1, "Moon"))
    pick = pick_spy_origin([o1, o2], Coords(1, 11, 1), {"a": 0, "b": 5}, 2)
    assert pick and pick.id == "b"
    ts = {"x": FarmTarget(Coords(1, 1, 1), STATE_PROBED, probed_at=time.time() - 99999)}
    prune_targets(ts, keep_minutes=1, now=time.time())
    assert ts["x"].state == STATE_PENDING
    home = [Celestial("1", "H", Coords(2, 100, 4))]
    dr = default_scan_range(home, 30)
    assert dr == [{"Galaxy": 2, "StartSystem": 70, "EndSystem": 130}]
    assert _cfg({}, "Active") is True
    assert _cfg({"Active": False}, "Active") is False
    print("autofarm ok")
