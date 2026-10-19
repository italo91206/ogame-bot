"""FleetCom TUI: boot splash + overview (celestials | comlog)."""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

import filelog
from game.resources import parse_ogame_int
from timefmt import fmt_duration, mask_seconds_in_text

_NORM_RE = re.compile(
    r" \(\d+\)$| · next (?:\d+d )?(?:\d+h )?(?:\d+m )?(?:\d+s)?$"
)

SHORTCUTS_RUN = "b browser · w workers · l logs · r reconfirm · Ctrl+C sair"
SHORTCUTS_INSPECT = "b voltar ao bot · w workers · l logs · Ctrl+C sair"
SHORTCUTS_LOGS = "l  fechar logs → overview"
SHORTCUTS_WORKERS = "↑↓ navegar · Space on/off · 1-9/a/c.. · w fechar"

_ACCENT = "cyan"
_BORDER = "dark_cyan"


@dataclass
class PlanetRow:
    name: str
    coords: str = ""
    metal: str = "?"
    crystal: str = "?"
    deut: str = "?"
    energy: str = "?"
    kind: str = ""  # Planet | Moon
    note: str = ""  # legado / livre
    last_action: str = "—"
    last_at: float = 0.0


@dataclass
class WorkerRow:
    name: str
    state: str = "idle"  # idle | running | waiting | off
    next_in: str = "-"
    reason: str = ""


def fmt_ago(ts: float, *, now: float | None = None) -> str:
    if not ts:
        return "—"
    age = max(0.0, (now if now is not None else time.time()) - ts)
    return f"{fmt_duration(age)} atrás"


def _short_action(msg: str) -> str:
    s = _NORM_RE.sub("", msg).strip()
    if ": " in s:
        s = s.split(": ", 1)[1]
    return s[:56] + ("…" if len(s) > 56 else "")


@dataclass
class BotTUI:
    universe: str = "?"
    status: str = "boot"
    health: str = ""
    planets: list[PlanetRow] = field(default_factory=list)
    workers: list[WorkerRow] = field(default_factory=list)
    logs: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=48))
    shortcuts: str = SHORTCUTS_RUN
    view: str = "dash"  # boot | dash | logs | workers
    log_tail: list[str] = field(default_factory=list)
    under_attack: str = ""  # detalhe; vazio = safe
    under_attack_n: int = 0  # qtd de ameaças ativas
    vacation: bool = False
    worker_sel: int = 0  # índice destacado na view workers
    _console: Console = field(default_factory=lambda: Console(stderr=False))
    _last_key: str = field(default="", repr=False)
    _last_repeat: int = field(default=0, repr=False)
    _boot_frame: object | None = field(default=None, repr=False)

    def log(self, msg: str, level: str = "info") -> None:
        msg = mask_seconds_in_text(msg)
        key = f"{level}\0{_NORM_RE.sub('', msg).rstrip()}"
        if self.logs and key == self._last_key:
            self._last_repeat += 1
            ts, _ = self.logs[0]
            base = _NORM_RE.sub("", msg).rstrip()
            self.logs[0] = (ts, f"[{level}] {base} ({self._last_repeat})")
            self._maybe_action(msg)
            return
        self._last_key = key
        self._last_repeat = 1
        self.logs.appendleft((datetime.now().strftime("%H:%M:%S"), f"[{level}] {msg}"))
        filelog.write(msg, level)
        self._maybe_action(msg)

    def _maybe_action(self, msg: str) -> None:
        """Se o log cita um celestial conhecido, grava última ação nele."""
        for p in self.planets:
            if p.name and p.name in msg:
                self.record_action(p.name, _short_action(msg))
                return

    def record_action(self, name: str, action: str) -> None:
        for p in self.planets:
            if p.name == name:
                p.last_action = action or "—"
                p.last_at = time.time()
                return

    def set_status(self, status: str) -> None:
        self.status = status

    def set_under_attack(self, detail: str = "", *, count: int = 0) -> None:
        detail = (detail or "").strip()
        self.under_attack = detail
        self.under_attack_n = max(0, int(count)) if detail else 0

    def _attack_banner(self) -> Text | None:
        if not self.under_attack:
            return None
        n = self.under_attack_n or 1
        title = f"SOB ATAQUE ×{n}" if n != 1 else "SOB ATAQUE ×1"
        msg = f" ⚠  {title}  —  {self.under_attack} "
        pad = max(72, len(msg) + 4)
        line = msg.ljust(pad)
        t = Text()
        blank = " " * pad
        t.append(blank + "\n", style="bold white on red")
        t.append(blank + "\n", style="bold white on red")
        t.append(line + "\n", style="bold white on red")
        t.append(blank + "\n", style="bold white on red")
        t.append(blank + "\n", style="bold white on red")
        return t

    def upsert_planet(self, name: str, **kwargs) -> None:
        for p in self.planets:
            if p.name == name:
                for k, v in kwargs.items():
                    if k in ("last_action", "last_at") and not v:
                        continue
                    setattr(p, k, v)
                return
        self.planets.append(PlanetRow(name=name, **kwargs))

    def set_workers(self, rows: list[WorkerRow]) -> None:
        self.workers = rows
        self._clamp_worker_sel()

    def show_log_tail(self, n: int = 50) -> None:
        self.log_tail = filelog.tail(n)
        self.view = "logs"
        self.shortcuts = SHORTCUTS_LOGS

    def show_workers(self) -> None:
        self.view = "workers"
        self.shortcuts = SHORTCUTS_WORKERS
        self._clamp_worker_sel()

    def hide_overlay(self, shortcuts: str = SHORTCUTS_RUN) -> None:
        self.view = "dash"
        self.shortcuts = shortcuts

    def _clamp_worker_sel(self) -> None:
        n = len(self.workers)
        if n <= 0:
            self.worker_sel = 0
        else:
            self.worker_sel = max(0, min(self.worker_sel, n - 1))

    def move_worker_sel(self, delta: int) -> None:
        if not self.workers:
            self.worker_sel = 0
            return
        self.worker_sel = (self.worker_sel + delta) % len(self.workers)

    def hide_log_tail(self, shortcuts: str = SHORTCUTS_RUN) -> None:
        self.hide_overlay(shortcuts)

    def _header(self, tag: str = "") -> Text:
        h_style = (
            "bold red"
            if self.health and ("stale" in self.health or "nunca" in self.health)
            else "dim"
        )
        status_style = "bold white on red" if self.under_attack else "yellow"
        if self.under_attack:
            n = self.under_attack_n or 1
            status_txt = f" │ SOB ATAQUE ×{n} · {self.status} "
        else:
            status_txt = f" │ {self.status} "
        parts = [
            ("◆ FLEETCOM ", f"bold {_ACCENT}"),
            (f" {self.universe.upper()} ", "bold white on dark_cyan"),
            (status_txt, status_style),
        ]
        if self.vacation:
            parts.append((" │ FÉRIAS ", "bold black on yellow"))
        if self.health:
            parts.append((f" │ {self.health} ", h_style))
        if tag:
            parts.append((f" │ {tag} ", "bold black on yellow"))
        return Text.assemble(*parts)

    def _footer(self) -> Text:
        return Text(f"  // {self.shortcuts}", style="dim cyan")

    def _totals(self) -> tuple[int, int, int]:
        m = c = d = 0
        for p in self.planets:
            m += parse_ogame_int(p.metal)
            c += parse_ogame_int(p.crystal)
            d += parse_ogame_int(p.deut)
        return m, c, d

    def _overview_panel(self) -> Panel:
        from game.resources import format_ogame_int

        now = time.time()
        tm, tc, td = self._totals()

        head = Text()
        head.append("RESERVES  ", style="bold dim")
        head.append(f"M {format_ogame_int(tm)}", style="bold red")
        head.append("  ·  ", style="dim")
        head.append(f"C {format_ogame_int(tc)}", style="bold cyan")
        head.append("  ·  ", style="dim")
        head.append(f"D {format_ogame_int(td)}", style="bold green")
        head.append(f"    nodes={len(self.planets)}\n", style="dim")

        pt = Table(expand=True, box=None, padding=(0, 1), show_header=True)
        pt.add_column("CELESTIAL", style="bold")
        pt.add_column("COORD", style="dim")
        pt.add_column("M", style="red", justify="right")
        pt.add_column("C", style="cyan", justify="right")
        pt.add_column("D", style="green", justify="right")
        pt.add_column("LAST ACTION", style="white")
        pt.add_column("WHEN", style="dim", justify="right")

        if not self.planets:
            pt.add_row("—", "", "", "", "", "aguardando scan…", "")
        else:
            for p in self.planets:
                mark = "☾" if (p.kind == "Moon" or " M" in p.coords) else "●"
                label = f"{mark} {p.name}"
                pt.add_row(
                    label,
                    p.coords,
                    p.metal,
                    p.crystal,
                    p.deut,
                    p.last_action or "—",
                    fmt_ago(p.last_at, now=now),
                )

        body = Group(head, Rule(style="dim cyan"), pt)
        return Panel(
            body,
            title="[bold cyan]// OVERVIEW · CELESTIAL GRID[/]",
            border_style=_BORDER,
            padding=(0, 1),
        )

    def _comlog_panel(self, n: int = 10) -> Panel:
        log_lines = Text()
        for ts, line in list(self.logs)[:n]:
            style = (
                "bold white on red"
                if "[error]" in line
                else "yellow"
                if "[warn]" in line
                else "green"
                if "[ok]" in line
                else "white"
            )
            log_lines.append(f"{ts} ", style="dim")
            log_lines.append(line + "\n", style=style)
        return Panel(
            log_lines if self.logs else Text("  channel idle — awaiting traffic", style="dim"),
            title="[bold cyan]// COMLOG[/]",
            border_style=_BORDER,
            padding=(0, 1),
        )

    def _workers_table(self) -> Table:
        from control import ACTIVE_PATH, index_key

        wt = Table(expand=True, box=None, padding=(0, 1))
        wt.add_column("#", style="dim", justify="right")
        wt.add_column("Worker", style="bold")
        wt.add_column("Estado")
        wt.add_column("Próximo")
        wt.add_column("Motivo")
        color = {"running": "green", "waiting": "yellow", "idle": "dim", "off": "red"}
        if not self.workers:
            wt.add_row("—", "—", "off", "-", "nenhum worker")
        else:
            for i, w in enumerate(self.workers):
                key = index_key(i) if w.name in ACTIVE_PATH else "·"
                sel = i == self.worker_sel
                mark = "▸" if sel else " "
                row_style = f"bold white on {_BORDER}" if sel else None
                state_style = (
                    f"bold white on {_BORDER}"
                    if sel
                    else color.get(w.state, "white")
                )
                wt.add_row(
                    Text(f"{mark}{key}", style=row_style or "dim"),
                    Text(w.name, style=row_style or "bold"),
                    Text(w.state, style=state_style),
                    Text(w.next_in, style=row_style),
                    Text(w.reason, style=row_style),
                    style=row_style,
                )
        return wt

    def _render_logs_view(self):
        body = Text()
        if not self.log_tail:
            body.append("sem logs no arquivo de hoje", style="dim")
        else:
            for line in self.log_tail:
                style = (
                    "bold white on red"
                    if "[error]" in line
                    else "yellow"
                    if "[warn]" in line
                    else "green"
                    if "[ok]" in line
                    else "white"
                )
                body.append(line + "\n", style=style)
        parts: list = [self._header(f"LOGS {len(self.log_tail)} · L sai")]
        ban = self._attack_banner()
        if ban is not None:
            parts.append(ban)
        parts.extend(
            [
                self._footer(),
                Panel(body, title="// ARCHIVE TAIL", border_style=_BORDER),
            ]
        )
        return Group(*parts)

    def _render_workers_view(self):
        n = len(self.workers)
        cur = (
            self.workers[self.worker_sel].name
            if n and 0 <= self.worker_sel < n
            else "—"
        )
        parts: list = [self._header(f"WORKERS {n} · {cur} · W sai")]
        ban = self._attack_banner()
        if ban is not None:
            parts.append(ban)
        parts.extend(
            [
                self._footer(),
                Panel(
                    self._workers_table(),
                    title="// SCHEDULER MATRIX",
                    border_style=_BORDER,
                ),
            ]
        )
        return Group(*parts)

    def render(self):
        if self.view == "boot" and self._boot_frame is not None:
            return self._boot_frame
        if self.view == "logs":
            return self._render_logs_view()
        if self.view == "workers":
            return self._render_workers_view()

        parts: list = [self._header()]
        ban = self._attack_banner()
        if ban is not None:
            parts.append(ban)
        parts.extend(
            [
                self._overview_panel(),
                self._comlog_panel(10),
                self._footer(),
            ]
        )
        return Group(*parts)

    def live(self) -> Live:
        return Live(self.render(), console=self._console, refresh_per_second=6, screen=True)


def demo() -> None:
    """Self-check visual sem browser."""
    t = BotTUI(universe="Demo")
    t.set_workers(
        [
            WorkerRow("Defender", "waiting", "12s", "poll ataques"),
            WorkerRow("Expeditions", "running", "—", "enviar expo 3/5"),
            WorkerRow("AutoMine", "waiting", "4m", "upgrade em progresso"),
            WorkerRow("AutoFarm", "off", "-", "Active=false"),
        ]
    )
    t.upsert_planet(
        "Home",
        coords="[1:2:3]",
        metal="1.2M",
        crystal="800k",
        deut="200k",
        energy="3.1k",
        kind="Planet",
    )
    t.upsert_planet(
        "Luna",
        coords="[1:2:3] M",
        metal="50k",
        crystal="40k",
        deut="10k",
        kind="Moon",
    )
    t.record_action("Home", "mina metal 12→13")
    assert "atrás" in fmt_ago(time.time() - 90) or "1m" in fmt_ago(time.time() - 90)

    with t.live() as live:
        from tui_boot import play_boot

        play_boot(t, live, universe="Demo", seconds=1.2)
        for i in range(4):
            t.set_status(f"running · tick {i}")
            t.log(f"AutoMine: Home tick {i}", "ok" if i % 2 == 0 else "info")
            live.update(t.render())
            time.sleep(0.2)

    assert t.view == "dash"
    home = next(p for p in t.planets if p.name == "Home")
    assert home.last_action != "—" and home.last_at > 0
    assert t._totals()[0] > 0

    t.show_workers()
    assert t.view == "workers"
    assert t.worker_sel == 0
    t.move_worker_sel(1)
    assert t.worker_sel == 1
    t.move_worker_sel(-1)
    assert t.worker_sel == 0
    t.hide_overlay()
    assert t.view == "dash"

    t2 = BotTUI()
    t2.log("Overview: scan 1 · slots 0/0 · next 71s", "ok")
    t2.log("Overview: scan 1 · slots 0/0 · next 59s", "ok")
    t2.log("Overview: scan 1 · slots 0/0 · next 64s", "ok")
    assert len(t2.logs) == 1 and "(3)" in t2.logs[0][1]
    t3 = BotTUI()
    t3.log("AutoCargo: nada a construir · next 6367s", "ok")
    assert "1h 46m 7s" in t3.logs[0][1]
    t2.show_log_tail(50)
    assert t2.view == "logs"
    t2.hide_log_tail()
    assert t2.view == "dash"
    t2.set_under_attack("2 ameaça(s) · ataque Bob→[1:2:3] 90s", count=2)
    assert t2._attack_banner() is not None
    assert "SOB ATAQUE ×2" in t2._header().plain
    assert "×2" in t2._attack_banner().plain
    t2.set_under_attack("")
    assert t2._attack_banner() is None and t2.under_attack_n == 0
    print("tui ok")


if __name__ == "__main__":
    demo()
