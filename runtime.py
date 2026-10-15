"""Session loop: tick due workers; reserve fleet slots for the player."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from game import FleetSlots, parse_slots

# Overview drop wake (E00-T09); OfferOfTheDay optional
BRAIN_WORKERS = frozenset(
    {
        "AutoMine",
        "AutoResearch",
        "LifeformAutoMine",
        "LifeformAutoResearch",
        "AutoCargo",
        "AutoRepatriate",
        "OfferOfTheDay",
    }
)


@dataclass
class Worker:
    name: str
    active: bool = True
    interval_min: float = 30.0  # seconds
    interval_max: float = 60.0
    _next_at: float = field(default=0.0, repr=False)
    _next_wait: float | None = field(default=None, repr=False)  # tick override
    reason: str = ""  # motivo do estado atual (TUI)

    def due(self, now: float | None = None) -> bool:
        return self.active and (now or time.time()) >= self._next_at

    def schedule_next(self, wait: float | None = None) -> float:
        if wait is None:
            wait = self._next_wait
        self._next_wait = None
        if wait is None:
            wait = random.uniform(self.interval_min, self.interval_max)
        else:
            wait = max(5.0, float(wait))
        self._next_at = time.time() + wait
        return wait

    def tick(self, ctx: dict[str, Any]) -> str:
        """Override. Return short status for TUI."""
        return "idle"


def slots_available(slots: FleetSlots, leave_free: int) -> bool:
    """True if sending a fleet still leaves `leave_free` slots for the player."""
    return slots.free > leave_free


def pick_schedule(
    waits: list[tuple[float, str]],
    interval_min: float,
    interval_max: float,
    *,
    empty_why: str = "planetList vazio — retry",
    empty_lo: float = 30.0,
    empty_hi: float = 90.0,
) -> tuple[float, str]:
    """Best wait among celestial reasons; empty list → short DOM retry (not CheckInterval)."""
    if waits:
        return min(waits, key=lambda t: t[0])
    return random.uniform(empty_lo, empty_hi), empty_why


def schedule_why(
    wait: float | None, why: str | None, interval_min: float, interval_max: float
) -> tuple[float, str] | None:
    """Keep real why even when wait is None (CheckInterval fallback)."""
    if not why:
        return None
    w = wait if wait is not None else random.uniform(interval_min, interval_max)
    return w, why


class Runtime:
    def __init__(self, workers: list[Worker], slots_to_leave_free: int = 1):
        # ponytail: _next_at=0 → first loop ticks now (TBot uses AFewSeconds stagger)
        self.workers = workers
        self.slots_to_leave_free = slots_to_leave_free

    def can_send_fleet(self, page) -> bool:
        return slots_available(parse_slots(page), self.slots_to_leave_free)

    def wake(self, names: frozenset[str] | set[str] | None = None) -> list[str]:
        """Schedule named active workers for immediate tick. Default: Brain."""
        want = names if names is not None else BRAIN_WORKERS
        now = time.time()
        woken: list[str] = []
        for w in self.workers:
            if w.active and w.name in want and w._next_at > now:
                w._next_at = 0.0
                woken.append(w.name)
        return woken

    def run_once(
        self,
        ctx: dict[str, Any],
        *,
        stop_when: Callable[[], bool] | None = None,
    ) -> list[tuple[str, str]]:
        """Tick every due worker. Returns [(name, status), ...].

        stop_when: if True before/after a tick, leave remaining due for next loop.
        """
        now = time.time()
        sleeping = bool(ctx.get("sleeping"))
        results: list[tuple[str, str]] = []
        for w in self.workers:
            if stop_when and stop_when():
                break
            # guards keep polling during sleep (TBot Defender stays up)
            if sleeping and w.name not in ("SleepMode", "Defender"):
                continue
            if not w.due(now):
                continue
            try:
                status = w.tick(ctx) or "ok"
            except Exception as e:
                status = f"error: {e}"
            # absolute deadline; tick may set w._next_wait (countdown / resource ETA)
            wait = w.schedule_next()
            results.append((w.name, f"{status} · next {wait:.0f}s"))
            if stop_when and stop_when():
                break
        return results

    def reconfirm(
        self,
        ctx: dict[str, Any],
        *,
        stop_when: Callable[[], bool] | None = None,
    ) -> list[tuple[str, str]]:
        """Force-tick every active worker now (recompute waits / act if ready)."""
        for w in self.workers:
            if w.active:
                w._next_at = 0.0
        return self.run_once(ctx, stop_when=stop_when)

    def loop(
        self,
        ctx: dict[str, Any],
        on_idle: Callable[[], None] | None = None,
        sleep_s: float = 1.0,
    ) -> None:
        while True:
            self.run_once(ctx)
            if on_idle:
                on_idle()
            time.sleep(sleep_s)


if __name__ == "__main__":
    assert slots_available(FleetSlots(2, 15), 1) is True
    assert slots_available(FleetSlots(1, 15), 1) is False
    assert slots_available(FleetSlots(0, 15), 1) is False
    assert FleetSlots(1, 2, 0, 1).exp_total == 1

    class _W(Worker):
        def tick(self, ctx):
            ctx["n"] = ctx.get("n", 0) + 1
            return "ticked"

    w = _W("t", interval_min=60, interval_max=60)
    rt = Runtime([w], slots_to_leave_free=1)
    assert w.due()  # start → immediate
    ctx: dict = {}
    assert rt.run_once(ctx)[0][0] == "t"
    assert ctx["n"] == 1
    assert not w.due()  # after tick, +60s
    w2 = _W("t2", interval_min=60, interval_max=60)
    w2._next_wait = 12
    assert w2.schedule_next() == 12
    assert pick_schedule([(10.0, "a"), (5.0, "b")], 60, 120) == (5.0, "b")
    w_empty, why_empty = pick_schedule([], 600, 1200)
    assert 30 <= w_empty <= 90 and "planetList" in why_empty
    assert schedule_why(None, "crystal gate", 60, 60) == (60.0, "crystal gate")
    assert schedule_why(12.0, "eta", 60, 60) == (12.0, "eta")
    assert schedule_why(None, None, 60, 60) is None
    w3 = _W("t3", interval_min=60, interval_max=60)
    w3._next_at = time.time() + 999
    rt2 = Runtime([w3], slots_to_leave_free=1)
    assert not w3.due()
    out = rt2.reconfirm({})
    assert out[0][0] == "t3" and "ticked" in out[0][1]
    a = _W("a", interval_min=60, interval_max=60)
    b = _W("b", interval_min=60, interval_max=60)
    rt_stop = Runtime([a, b])
    flag = {"n": 0}

    def _stop():
        flag["n"] += 1
        return flag["n"] > 1  # abort before second worker

    stopped = rt_stop.run_once({}, stop_when=_stop)
    assert [n for n, _ in stopped] == ["a"] and b.due()
    brain = _W("AutoMine", interval_min=60, interval_max=60)
    brain._next_at = time.time() + 999
    other = _W("Expeditions", interval_min=60, interval_max=60)
    other._next_at = time.time() + 999
    rt3 = Runtime([brain, other])
    assert rt3.wake() == ["AutoMine"]
    assert brain.due() and not other.due()
    sleep_w = _W("SleepMode", interval_min=60, interval_max=60)
    other2 = _W("AutoMine", interval_min=60, interval_max=60)
    rt4 = Runtime([sleep_w, other2])
    ctx_s: dict = {"sleeping": True, "n": 0}
    out_s = rt4.run_once(ctx_s)
    assert [n for n, _ in out_s] == ["SleepMode"]
    assert ctx_s["n"] == 1
    print("runtime ok")
