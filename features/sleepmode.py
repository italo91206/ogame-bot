"""E01 SleepMode T01+T02+T03: sleep window, defer fleets, AutoFleetSave."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, time
from typing import Any

from features.fleetsave import fleetsave_celestial, process_recalls
from game import parse_celestials
from game.fleet import fleets_delay_until_sleep
from runtime import Worker


def parse_hhmm(s: str) -> time:
    return datetime.strptime(s.strip(), "%H:%M").time()


def in_sleep_window(now_t: time, go: time, wake: time) -> bool:
    if go == wake:
        return False
    if go < wake:
        return go <= now_t < wake
    return now_t >= go or now_t < wake


def secs_until(now: datetime, target: time) -> float:
    t = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    if t <= now:
        t += timedelta(days=1)
    return (t - now).total_seconds()


class SleepModeWorker(Worker):
    """Always scheduled; settings.Active gates behavior (clears sleeping when off)."""

    def tick(self, ctx: dict[str, Any]) -> str:
        cfg = (ctx.get("settings") or {}).get("SleepMode") or {}
        tui = ctx.get("tui")
        if not cfg.get("Active"):
            if ctx.get("sleeping"):
                ctx["sleeping"] = False
                if tui:
                    tui.log("SleepMode: off → acordado", "ok")
            else:
                ctx["sleeping"] = False
            self.reason = "off"
            self._next_wait = 300.0
            return self.reason

        try:
            go = parse_hhmm(str(cfg.get("GoToSleep") or ""))
            wake = parse_hhmm(str(cfg.get("WakeUp") or ""))
        except ValueError:
            ctx["sleeping"] = False
            self.reason = "hora inválida"
            self._next_wait = 300.0
            return self.reason

        if go == wake:
            ctx["sleeping"] = False
            self.reason = "GoToSleep == WakeUp"
            self._next_wait = 300.0
            return self.reason

        now = datetime.now()
        asleep = in_sleep_window(now.time(), go, wake)
        edge = wake if asleep else go
        until = secs_until(now, edge)
        jitter = random.uniform(30.0, 120.0)

        page = ctx.get("page")
        recalls = ctx.setdefault("fleet_recalls", [])
        if page is not None:
            try:
                process_recalls(page, recalls, tui)
            except Exception as e:
                if tui:
                    tui.log(f"SleepMode: recall fail: {e}", "warn")

        if not asleep:
            was = bool(ctx.get("sleeping"))
            ctx["sleeping"] = False
            self._next_wait = until + jitter
            self.reason = f"acordado · sleep {go.strftime('%H:%M')}"
            if was:
                rt = ctx.get("runtime")
                if rt:
                    for w in rt.workers:
                        if w.name != "SleepMode" and w.active:
                            w._next_at = 0.0
                if tui:
                    tui.log(
                        f"SleepMode: acordou · próximo sono {go.strftime('%H:%M')}",
                        "ok",
                    )
            return self.reason

        # want sleep — maybe defer for fleets
        if cfg.get("PreventIfThereAreFleets"):
            delay = 0.0
            if page is not None:
                try:
                    delay = fleets_delay_until_sleep(page, until)
                except Exception:
                    delay = 0.0
            if delay > 0:
                ctx["sleeping"] = False
                self._next_wait = delay + random.uniform(5.0, 30.0)
                self.reason = f"adiado · frotas {delay:.0f}s"
                if tui:
                    tui.log(f"SleepMode: frotas ativas — recheck em {delay:.0f}s", "warn")
                return self.reason

        was = bool(ctx.get("sleeping"))
        ctx["sleeping"] = True
        self._next_wait = until + jitter
        self.reason = f"dormindo · wake {wake.strftime('%H:%M')}"
        if not was and tui:
            tui.log(f"SleepMode: dormindo até {wake.strftime('%H:%M')}", "warn")

        afs = cfg.get("AutoFleetSave") or {}
        if (
            not was
            and isinstance(afs, dict)
            and afs.get("Active")
            and page is not None
        ):
            only_moons = bool(afs.get("OnlyMoons"))
            deut_leave = int(afs.get("DeutToLeave") or 0)
            try:
                celestials = parse_celestials(page)
            except Exception as e:
                if tui:
                    tui.log(f"SleepMode: fleetsave parse fail: {e}", "warn")
                celestials = []
            targets = [
                c
                for c in celestials
                if (not only_moons) or c.coords.type == "Moon"
            ]
            saved = 0
            for c in targets:
                try:
                    status = fleetsave_celestial(
                        page,
                        c,
                        celestials,
                        min_duration=until,
                        deut_to_leave=deut_leave,
                        build_cargos=False,
                        default_mission=str(afs.get("DefaultMission") or "Deploy"),
                        recall=bool(afs.get("Recall")),
                        recalls=recalls,
                    )
                except Exception as e:
                    status = f"fail: {e}"
                if status.startswith("ok"):
                    saved += 1
                if tui:
                    tui.log(
                        f"SleepMode: fleetsave {status}",
                        "ok" if status.startswith("ok") else "warn",
                    )
            if saved:
                self.reason = f"dormindo · save {saved} · wake {wake.strftime('%H:%M')}"
        return self.reason


if __name__ == "__main__":
    assert in_sleep_window(time(0, 30), time(23, 15), time(7, 5)) is True
    assert in_sleep_window(time(12, 0), time(23, 15), time(7, 5)) is False
    assert in_sleep_window(time(15, 0), time(14, 0), time(16, 0)) is True
    assert in_sleep_window(time(13, 0), time(14, 0), time(16, 0)) is False
    assert in_sleep_window(time(10, 0), time(10, 0), time(10, 0)) is False
    base = datetime(2026, 10, 7, 23, 30, 0)
    assert secs_until(base, time(7, 5)) == 7 * 3600 + 35 * 60
    assert parse_hhmm("23:15") == time(23, 15)
    print("sleepmode ok")
