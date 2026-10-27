"""Handlers Telegram do runtime (ping/status/pause/sleep)."""
from __future__ import annotations

from typing import Any, Callable

from features.sleepmode import (
    clear_telegram_sleep,
    request_telegram_sleep,
    sleep_status_line,
)


def install(
    tg: Any,
    *,
    ctx: dict,
    headless: bool,
    runtime: Any,
    tui: Any,
    dom_health: Any,
    paused: list,
    pause_workers: Callable[[], str | None],
    resume_workers: Callable[[], str | None],
    is_inspecting: Callable[[], bool],
    is_recovering: Callable[[], bool],
) -> None:
    tg.status_fn = lambda: sleep_status_line(ctx)
    tg.commands.update(
        {
            "/ping": lambda: (
                f"pong · {tg.uptime()}{tg.status_extra()}"
            ),
            "/status": lambda: (
                f"uptime {tg.uptime()}\n"
                f"sleep: {sleep_status_line(ctx)}\n"
                f"headless={headless} inspect={is_inspecting()} "
                f"recover={is_recovering()}\n"
                f"workers on="
                f"{sum(1 for w in runtime.workers if w.active)}/"
                f"{len(runtime.workers)}\n"
                f"health {dom_health.status_line()}\n"
                + (
                    f"SOB ATAQUE ×{tui.under_attack_n or 1}: "
                    f"{tui.under_attack}"
                    if tui.under_attack
                    else "ataque: safe"
                )
            ),
            "/pause": lambda: (
                "já em inspect/recover"
                if is_inspecting() or is_recovering()
                else (pause_workers() or "workers pausados")
            ),
            "/resume": lambda: (
                "inspect — no desktop: tecla b"
                if is_inspecting()
                else "recover em andamento"
                if is_recovering()
                else (
                    (resume_workers() or "workers retomados")
                    if paused
                    else "nada pausado"
                )
            ),
            "/sleep": lambda: request_telegram_sleep(ctx),
            "/wakeup": lambda: clear_telegram_sleep(ctx),
        }
    )
