"""E01 SleepMode T01+T02+T03: sleep window, defer fleets, AutoFleetSave + /sleep."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, time
from typing import Any

from features.fleetsave import fleetsave_celestial, process_recalls
from game import parse_celestials
from game.fleet import fleets_delay_until_sleep, fleets_max_eta, recall_all_fleets
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


def next_wake_datetime(now: datetime, wake: time) -> datetime:
    t = now.replace(hour=wake.hour, minute=wake.minute, second=0, microsecond=0)
    if t <= now:
        t += timedelta(days=1)
    return t


def _kick_sleep_worker(ctx: dict[str, Any]) -> None:
    rt = ctx.get("runtime")
    if not rt:
        return
    for w in rt.workers:
        if w.name == "SleepMode":
            w._next_at = 0.0
            break


def sleep_status_line(ctx: dict[str, Any]) -> str:
    """Uma linha p/ TUI / Telegram (/status, /ping, autopping)."""
    force = ctx.get("force_sleep_until")
    if isinstance(force, datetime):
        wake = force.strftime("%H:%M")
        if ctx.get("force_sleep_need_save"):
            if not ctx.get("force_sleep_recalled"):
                phase = "recall"
            else:
                phase = "aguarda frota/save"
        else:
            phase = "dormindo"
        return f"/sleep {phase} · wake {wake}"
    if ctx.get("sleeping"):
        return "dormindo (janela SleepMode)"
    return "acordado"


def _refresh_tui_sleep(ctx: dict[str, Any]) -> None:
    tui = ctx.get("tui")
    if not tui:
        return
    cur = str(getattr(tui, "status", "") or "")
    if "inspect" in cur or cur.startswith("férias") or cur == "stopped":
        return
    line = sleep_status_line(ctx)
    tui.set_status("running" if line == "acordado" else line)


def request_telegram_sleep(ctx: dict[str, Any]) -> str:
    """Fila /sleep: recall → espera frota → fleetsave → dorme até WakeUp."""
    if ctx.get("force_sleep_until"):
        return sleep_status_line(ctx) + " (já na fila)"
    cfg = (ctx.get("settings") or {}).get("SleepMode") or {}
    try:
        wake = parse_hhmm(str(cfg.get("WakeUp") or ""))
    except ValueError:
        return "WakeUp inválido em SleepMode"
    until = next_wake_datetime(datetime.now(), wake)
    ctx["force_sleep_until"] = until
    ctx["force_sleep_need_save"] = True
    ctx["force_sleep_recalled"] = False
    ctx["sleeping"] = True  # para workers que mandam frota já no próximo tick
    _kick_sleep_worker(ctx)
    _refresh_tui_sleep(ctx)
    return f"sleep armado · wake {until.strftime('%H:%M %d/%m')}"


def clear_telegram_sleep(ctx: dict[str, Any]) -> str:
    """ /wakeup — cancela fila forçada e acorda."""
    had = bool(ctx.pop("force_sleep_until", None))
    ctx.pop("force_sleep_need_save", None)
    ctx.pop("force_sleep_recalled", None)
    was = bool(ctx.get("sleeping"))
    ctx["sleeping"] = False
    rt = ctx.get("runtime")
    if rt:
        for w in rt.workers:
            if w.name != "SleepMode" and w.active:
                w._next_at = 0.0
    _kick_sleep_worker(ctx)
    _refresh_tui_sleep(ctx)
    if had or was:
        return "acordado"
    return "já acordado"


def _fleetsave_targets(
    celestials: list, *, only_moons: bool, prefer_moons: bool
) -> list:
    if only_moons:
        return [c for c in celestials if c.coords.type == "Moon"]
    if prefer_moons:
        moons = [c for c in celestials if c.coords.type == "Moon"]
        return moons or list(celestials)
    return list(celestials)


def _run_autofleetsave(
    page: Any,
    afs: dict,
    *,
    min_duration: float,
    recalls: list,
    tui: Any,
    prefer_moons: bool = False,
) -> int:
    only_moons = bool(afs.get("OnlyMoons"))
    deut_leave = int(afs.get("DeutToLeave") or 0)
    try:
        celestials = parse_celestials(page)
    except Exception as e:
        if tui:
            tui.log(f"SleepMode: fleetsave parse fail: {e}", "warn")
        return 0
    targets = _fleetsave_targets(
        celestials, only_moons=only_moons, prefer_moons=prefer_moons
    )
    saved = 0
    for c in targets:
        try:
            status = fleetsave_celestial(
                page,
                c,
                celestials,
                min_duration=min_duration,
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
    return saved


class SleepModeWorker(Worker):
    """Always scheduled; settings.Active gates behavior (clears sleeping when off)."""

    def tick(self, ctx: dict[str, Any]) -> str:
        try:
            return self._tick(ctx)
        finally:
            _refresh_tui_sleep(ctx)

    def _tick(self, ctx: dict[str, Any]) -> str:
        cfg = (ctx.get("settings") or {}).get("SleepMode") or {}
        tui = ctx.get("tui")
        now = datetime.now()
        force_until = ctx.get("force_sleep_until")
        if isinstance(force_until, datetime) and now >= force_until:
            ctx.pop("force_sleep_until", None)
            ctx.pop("force_sleep_need_save", None)
            ctx.pop("force_sleep_recalled", None)
            force_until = None
            if ctx.get("sleeping"):
                ctx["sleeping"] = False
                rt = ctx.get("runtime")
                if rt:
                    for w in rt.workers:
                        if w.name != "SleepMode" and w.active:
                            w._next_at = 0.0
                if tui:
                    tui.log("SleepMode: /sleep acabou · acordou", "ok")

        forced = isinstance(force_until, datetime)

        if not cfg.get("Active") and not forced:
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
            if not forced:
                ctx["sleeping"] = False
                self.reason = "hora inválida"
                self._next_wait = 300.0
                return self.reason
            go = wake = time(0, 0)

        if not forced and go == wake:
            ctx["sleeping"] = False
            self.reason = "GoToSleep == WakeUp"
            self._next_wait = 300.0
            return self.reason

        asleep = forced or in_sleep_window(now.time(), go, wake)
        if forced:
            until = max(1.0, (force_until - now).total_seconds())
            wake_label = force_until.strftime("%H:%M")
        else:
            edge = wake if asleep else go
            until = secs_until(now, edge)
            wake_label = wake.strftime("%H:%M")
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

        # --- /sleep forçado: recall → wait → fleetsave ---
        if forced and ctx.get("force_sleep_need_save"):
            ctx["sleeping"] = True
            if page is not None and not ctx.get("force_sleep_recalled"):
                try:
                    ok, fail = recall_all_fleets(page)
                except Exception as e:
                    ok, fail = 0, 0
                    if tui:
                        tui.log(f"SleepMode: /sleep recall fail: {e}", "warn")
                ctx["force_sleep_recalled"] = True
                if tui and (ok or fail):
                    tui.log(f"SleepMode: /sleep recall ok={ok} fail={fail}", "warn")
                self._next_wait = random.uniform(15.0, 40.0)
                self.reason = f"sleep · recall · wake {wake_label}"
                return self.reason

            delay = 0.0
            if page is not None:
                try:
                    delay = fleets_max_eta(page)
                except Exception:
                    delay = 0.0
            if delay > 5:
                self._next_wait = delay + random.uniform(5.0, 30.0)
                self.reason = f"sleep · frota {delay:.0f}s · wake {wake_label}"
                if tui:
                    tui.log(
                        f"SleepMode: /sleep aguarda frota {delay:.0f}s",
                        "warn",
                    )
                return self.reason

            afs = cfg.get("AutoFleetSave") or {}
            if not isinstance(afs, dict):
                afs = {}
            saved = 0
            if page is not None:
                saved = _run_autofleetsave(
                    page,
                    afs,
                    min_duration=until,
                    recalls=recalls,
                    tui=tui,
                    prefer_moons=True,
                )
            ctx["force_sleep_need_save"] = False
            self._next_wait = until + jitter
            self.reason = (
                f"dormindo · save {saved} · wake {wake_label}"
                if saved
                else f"dormindo · wake {wake_label}"
            )
            if tui:
                tui.log(f"SleepMode: /sleep dormindo até {wake_label}", "warn")
            return self.reason

        # want sleep — maybe defer for fleets (janela natural)
        if not forced and cfg.get("PreventIfThereAreFleets"):
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
        self.reason = f"dormindo · wake {wake_label}"
        if not was and tui:
            tui.log(f"SleepMode: dormindo até {wake_label}", "warn")

        afs = cfg.get("AutoFleetSave") or {}
        if (
            not was
            and not forced
            and isinstance(afs, dict)
            and afs.get("Active")
            and page is not None
        ):
            saved = _run_autofleetsave(
                page,
                afs,
                min_duration=until,
                recalls=recalls,
                tui=tui,
                prefer_moons=False,
            )
            if saved:
                self.reason = f"dormindo · save {saved} · wake {wake_label}"
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
    assert next_wake_datetime(base, time(7, 5)).hour == 7
    ctx: dict = {}
    ctx["settings"] = {"SleepMode": {"WakeUp": "08:00"}}
    assert sleep_status_line(ctx) == "acordado"
    msg = request_telegram_sleep(ctx)
    assert "sleep armado" in msg and ctx.get("force_sleep_until")
    assert "/sleep" in sleep_status_line(ctx) and "wake" in sleep_status_line(ctx)
    assert "acordado" in clear_telegram_sleep(ctx)
    assert ctx.get("force_sleep_until") is None
    print("sleepmode ok")
