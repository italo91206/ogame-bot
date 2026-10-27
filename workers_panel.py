"""Overlay workers: rascunho Active + perfis Focus (mantém main enxuto)."""
from __future__ import annotations

from typing import Any, Callable

import control
import focus
from features.overview import worker_rows
from tui import SHORTCUTS_WORKERS, BotTUI


def shortcuts_for(settings: dict, *, naming: str | None = None) -> str:
    if naming is not None:
        return f"nome: {naming}_ · Enter salva · Esc cancela"
    cur = focus.current_name(settings)
    return f"{SHORTCUTS_WORKERS} · g geral · ]/[ perfil · s salva · [{cur}]"


class WorkersPanel:
    def __init__(
        self,
        *,
        tui: BotTUI,
        settings: dict,
        runtime: Any,
        stubs: list,
        boot_active: set[str],
        paused: list,
        tick: Callable[..., None],
        live: Any,
    ) -> None:
        self.tui = tui
        self.settings = settings
        self.runtime = runtime
        self.stubs = stubs
        self.boot_active = boot_active
        self.paused = paused
        self.tick = tick
        self.live = live
        self.draft: dict[str, bool] = {}
        self.naming: str | None = None  # None = normal; str = buffer do nome

    def _kw(self) -> dict:
        return {"boot_active": self.boot_active, "paused": self.paused}

    def paint(self) -> None:
        # menu = Active do settings ∪ rascunho (não runtime: pause/inspect mentiria)
        rows = worker_rows(self.runtime.workers, self.stubs)
        for r in rows:
            on = control.draft_active(self.draft, self.settings, r.name)
            if on is None:
                continue
            if on:
                if r.state == "off":
                    r.state = "running"
                    r.next_in = "-"
                if r.name in self.draft:
                    r.reason = "rascunho"
                elif r.reason in ("", "off"):
                    r.reason = "on"
            else:
                r.state = "off"
                r.next_in = "-"
                r.reason = "rascunho off" if r.name in self.draft else "off"
        self.tui.set_workers(rows)
        self.tui.shortcuts = shortcuts_for(self.settings, naming=self.naming)
        self.tui.focus_name = focus.current_name(self.settings)

    def flush_draft(self) -> None:
        if not self.draft:
            return
        n = len(self.draft)
        control.apply_draft(
            self.draft, self.settings, self.runtime, **self._kw()
        )
        self.tick(f"workers: {n} alteração(ões) aplicadas", "ok")

    def open(self) -> None:
        self.draft.clear()
        self.naming = None
        self.paint()
        self.tui.show_workers()
        self.tui.shortcuts = shortcuts_for(self.settings)

    def close(self, sc: str) -> None:
        self.flush_draft()
        self.naming = None
        self.tui.hide_overlay(sc)

    def stage(self, idx: int) -> None:
        control.stage_toggle_at(self.draft, self.settings, self.runtime, idx)
        self.paint()
        self.live.update(self.tui.render())

    def apply_named(self, name: str) -> None:
        self.draft.clear()
        msgs = focus.apply_profile(
            self.settings, self.runtime, name, **self._kw()
        )
        self.tick(f"perfil '{focus.current_name(self.settings)}' aplicado", "ok")
        for m in msgs[:3]:
            self.tick(m, "info")
        if len(msgs) > 3:
            self.tick(f"… +{len(msgs) - 3} workers", "info")
        self.paint()
        self.live.update(self.tui.render())

    def start_save(self) -> None:
        self.naming = ""
        self.paint()
        self.live.update(self.tui.render())

    def handle_naming_key(self, key: str) -> bool:
        """True se consumiu a tecla (modo nome)."""
        if self.naming is None:
            return False
        if key in ("\x1b",):  # Esc
            self.naming = None
            self.paint()
            self.live.update(self.tui.render())
            return True
        if key in ("\r", "\n"):
            name = focus.validate_name(self.naming)
            if not name:
                self.tick("perfil: nome inválido", "warn")
                self.naming = None
                self.paint()
                self.live.update(self.tui.render())
                return True
            snap = focus.snapshot(self.settings, self.draft)
            self.flush_draft()
            msg = focus.save_profile(self.settings, name, snap)
            self.tick(msg, "ok" if "salvo" in msg else "warn")
            self.naming = None
            self.paint()
            self.live.update(self.tui.render())
            return True
        if key in ("\b", "\x08"):
            self.naming = self.naming[:-1]
            self.paint()
            self.live.update(self.tui.render())
            return True
        if len(key) == 1 and key.isprintable() and key not in "\t":
            if len(self.naming) < 24:
                self.naming += key.lower()
            self.paint()
            self.live.update(self.tui.render())
            return True
        return True  # engole resto no modo nome

    def handle_key(self, key: str) -> bool:
        """True se consumiu. Chamar só com view==workers."""
        if self.handle_naming_key(key):
            return True
        if key in ("up", "down"):
            self.tui.move_worker_sel(-1 if key == "up" else 1)
            self.live.update(self.tui.render())
            return True
        if key in (" ", "\r"):
            self.stage(self.tui.worker_sel)
            return True
        if key == "g":
            self.apply_named("geral")
            return True
        if key == "]":
            self.apply_named(focus.cycle_profile(self.settings, delta=1))
            return True
        if key == "[":
            self.apply_named(focus.cycle_profile(self.settings, delta=-1))
            return True
        if key == "s":
            self.start_save()
            return True
        if key and key not in "blwr":
            idx = control.key_to_index(key)
            if idx is not None:
                if 0 <= idx < len(self.tui.workers):
                    self.tui.worker_sel = idx
                self.stage(idx)
                return True
        return False
