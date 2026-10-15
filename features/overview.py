"""Overview worker + linhas TUI dos workers."""
from __future__ import annotations

import time

from game import ResourceBook, parse_slots, scan_all_resources
from runtime import Runtime, Worker, slots_available
from timefmt import fmt_duration, mask_seconds_in_text
from tui import BotTUI, WorkerRow


class OverviewWorker(Worker):
    def tick(self, ctx) -> str:
        page = ctx["page"]
        tui: BotTUI = ctx["tui"]
        book: ResourceBook = ctx["resources"]
        leave = ctx["slots_to_leave_free"]
        runtime: Runtime = ctx.get("runtime")

        scanned = scan_all_resources(page)
        slots = parse_slots(page)

        jumped = False
        for c, res, prod in scanned:
            if book.put(c, res, prod):
                jumped = True
        book.push_tui(tui)

        free_ok = slots_available(slots, leave)
        n = len(scanned)
        tui.set_status(
            f"running · slots {slots.free}/{slots.total} "
            f"(leave {leave}){' · ok' if free_ok else ' · reservado'}"
        )
        self.reason = f"scan {n} · slots {slots.free}/{slots.total}"
        if n == 0:
            self.reason = "scan 0 — DOM morto?"
        elif jumped and runtime:
            woken = runtime.wake()
            if woken:
                self.reason += f" · wake {','.join(woken)}"
                tui.log(f"overview: drop → wake {', '.join(woken)}", "ok")
        return self.reason


def worker_rows(
    workers: list[Worker], extras: list[WorkerRow] | None = None
) -> list[WorkerRow]:
    rows: list[WorkerRow] = []
    for w in workers:
        wait = max(0, w._next_at - time.time())
        state = "off" if not w.active else ("waiting" if wait > 0 else "running")
        reason = w.reason or ("off" if not w.active else "-")
        rows.append(
            WorkerRow(
                w.name,
                state,
                fmt_duration(wait) if w.active else "-",
                mask_seconds_in_text(reason),
            )
        )
    if extras:
        rows.extend(extras)
    return rows
