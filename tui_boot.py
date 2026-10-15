"""FleetCom boot / splash — estético, sem I/O de jogo."""
from __future__ import annotations

import random
import time
from typing import Any

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

_SIGIL = r"""
        .  ·  *    F L E E T C O M    *  ·  .
     ───◆───  OGAME RELAY  /  SECURE LINK  ───◆───
"""

_FLAVOR = (
    "scanning Lagrange debris fields…",
    "handshake: hyperspace sync pulse",
    "auth token · rotating cipher pads",
    "uplink jitter compensation…",
    "sector beacon α locked",
    "routing via dark-matter mesh",
    "probe telemetry checksum OK",
    "navcore ephemeris loaded",
    "plasma conductor warm-up",
    "COMSEC: one-time pad primed",
    "docking clamps soft-lock",
    "listening on fleet channel 7",
)

_STEPS = (
    ("INIT", "relay kernel"),
    ("LINK", "universe gate"),
    ("AUTH", "session cipher"),
    ("SYNC", "celestial map"),
    ("ARM", "worker schedulers"),
)


def _bar(pct: float, width: int = 28) -> str:
    filled = max(0, min(width, int(round(pct * width))))
    return "█" * filled + "░" * (width - filled)


def boot_frame(
    *,
    universe: str,
    step_i: int,
    pct: float,
    flavor: str,
    lat_ms: int,
    node: str,
) -> Group:
    title = Text()
    title.append(_SIGIL.strip("\n") + "\n", style="bold cyan")
    title.append("  NODE ", style="dim")
    title.append(node, style="bold green")
    title.append("  ·  TARGET ", style="dim")
    title.append(universe.upper(), style="bold yellow")
    title.append("\n")

    body = Text()
    body.append("  FLEETCOM CONNECTING", style="bold white")
    body.append("  ···\n\n", style="cyan")

    for i, (code, label) in enumerate(_STEPS):
        if i < step_i:
            mark, style = "OK", "green"
        elif i == step_i:
            mark, style = "··", "yellow"
        else:
            mark, style = "  ", "dim"
        body.append(f"  [{mark}] ", style=style)
        body.append(f"{code:<4} ", style="bold " + style if i <= step_i else "dim")
        body.append(f"{label}\n", style=style if i <= step_i else "dim")

    body.append("\n  ")
    body.append(_bar(pct), style="cyan")
    body.append(f"  {int(pct * 100):3d}%\n", style="bold white")
    body.append(f"\n  > {flavor}\n", style="dim italic")
    body.append(f"  lat={lat_ms}ms  ·  channel=HARVEST/EXPO/BRAIN\n", style="dim")

    panel = Panel(
        Align.left(Group(title, body)),
        title="[bold cyan]// BOOTSTRAP[/]",
        subtitle="[dim]awaiting uplink[/]",
        border_style="cyan",
        padding=(1, 2),
    )
    return Group(Align.center(panel))


def play_boot(tui: Any, live: Any, *, universe: str, seconds: float = 2.8) -> None:
    """Anima splash dentro do Live já aberto; depois deixa view=dash."""
    tui.view = "boot"
    node = f"α-{random.randint(1, 12)}"
    n_frames = max(8, int(seconds * 8))
    t0 = time.time()
    for i in range(n_frames):
        elapsed = time.time() - t0
        pct = min(1.0, (i + 1) / n_frames)
        step_i = min(len(_STEPS) - 1, int(pct * len(_STEPS)))
        frame = boot_frame(
            universe=universe or "?",
            step_i=step_i,
            pct=pct,
            flavor=random.choice(_FLAVOR),
            lat_ms=random.randint(4, 48),
            node=node,
        )
        tui._boot_frame = frame
        live.update(tui.render())
        # pacing: mais lento no fim
        time.sleep(0.05 + 0.04 * (1.0 - pct) + random.uniform(0, 0.03))
        if elapsed > seconds + 0.5:
            break
    tui.view = "dash"
    tui._boot_frame = None
    tui.set_status("uplink · ready")
    tui.log("FLEETCOM uplink established", "ok")
    live.update(tui.render())


if __name__ == "__main__":
    assert len(_bar(0.5, 10)) == 10
    assert "█" in _bar(1.0, 4)
    f = boot_frame(
        universe="Athena",
        step_i=2,
        pct=0.55,
        flavor="test",
        lat_ms=12,
        node="α-3",
    )
    assert f is not None
    print("tui_boot ok")
