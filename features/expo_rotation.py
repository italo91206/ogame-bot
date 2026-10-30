"""E03-T05: a cada N rounds de expo, destino = origin.system + offset; reset no dia civil."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from config import ROOT
from game.galaxy import clamp_system

STATE_PATH = ROOT / "expo_rotation.json"
ROUNDS_PER_STEP = 2


def _today() -> str:
    return date.today().isoformat()


def fresh() -> dict[str, Any]:
    return {"day": _today(), "sends": 0, "rounds": 0, "offset": 0}


def load(path: Path = STATE_PATH) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return fresh()
    if str(raw.get("day") or "") != _today():
        return fresh()
    return {
        "day": _today(),
        "sends": int(raw.get("sends") or 0),
        "rounds": int(raw.get("rounds") or 0),
        "offset": int(raw.get("offset") or 0),
    }


def save(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.write_text(json.dumps(state, ensure_ascii=True), encoding="utf-8")


def dest_system(origin_system: int, offset: int, n_systems: int = 499) -> int:
    return clamp_system(int(origin_system) + int(offset), n_systems)


def note_send(
    state: dict[str, Any],
    exp_total: int,
    *,
    rounds_per_step: int = ROUNDS_PER_STEP,
) -> dict[str, Any]:
    """1 round = exp_total envios ok; a cada rounds_per_step → offset+1."""
    if str(state.get("day") or "") != _today():
        state = fresh()
    need = max(1, int(exp_total))
    step = max(1, int(rounds_per_step))
    state["sends"] = int(state.get("sends") or 0) + 1
    if state["sends"] >= need:
        state["sends"] = 0
        state["rounds"] = int(state.get("rounds") or 0) + 1
        if state["rounds"] >= step:
            state["rounds"] = 0
            state["offset"] = int(state.get("offset") or 0) + 1
    state["day"] = _today()
    return state


if __name__ == "__main__":
    st = fresh()
    # exp_total=4, 2 rounds → offset 1 após 8 envios
    for _ in range(8):
        st = note_send(st, 4, rounds_per_step=2)
    assert st["offset"] == 1 and st["sends"] == 0 and st["rounds"] == 0
    assert dest_system(77, 1) == 78
    assert dest_system(499, 1) == 1
    # dia diferente → fresh
    st["day"] = "2000-01-01"
    st = note_send(st, 4)
    assert st["offset"] == 0 and st["sends"] == 1 and st["day"] == _today()
    print("expo_rotation ok")
