"""Runtime worker Active toggles → settings.json (ponte mínima)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from config import DEFAULT_SETTINGS, ROOT

# tecla → índice; sem b/l/w/r (atalhos do main)
_INDEX_KEYS = "123456789acdefghijkmnopqstuvxyz"

# worker.name → path até a chave Active no JSON
ACTIVE_PATH: dict[str, tuple[str, ...]] = {
    "SleepMode": ("SleepMode", "Active"),
    "Defender": ("Defender", "Active"),
    "Expeditions": ("Expeditions", "Active"),
    "AutoFarm": ("AutoFarm", "Active"),
    "AutoHarvest": ("AutoHarvest", "Active"),
    "AutoColonize": ("AutoColonize", "Active"),
    "AutoDiscovery": ("AutoDiscovery", "Active"),
    "AutoMine": ("Brain", "AutoMine", "Active"),
    "AutoResearch": ("Brain", "AutoResearch", "Active"),
    "LifeformAutoMine": ("Brain", "LifeformAutoMine", "Active"),
    "LifeformAutoResearch": ("Brain", "LifeformAutoResearch", "Active"),
    "AutoCargo": ("Brain", "AutoCargo", "Active"),
    "AutoRepatriate": ("Brain", "AutoRepatriate", "Active"),
}

# só grava settings; Runtime.active fica (ex.: SleepMode sempre agenda)
_SETTINGS_ONLY = frozenset({"SleepMode"})


def settings_file(path: Path | None = None) -> Path:
    return path or Path(os.environ.get("SETTINGS_PATH", DEFAULT_SETTINGS))


def key_to_index(ch: str) -> int | None:
    if len(ch) != 1:
        return None
    i = _INDEX_KEYS.find(ch.lower())
    return i if i >= 0 else None


def index_key(i: int) -> str:
    return _INDEX_KEYS[i] if 0 <= i < len(_INDEX_KEYS) else "?"


def _get(d: dict, path: tuple[str, ...], default: Any = None) -> Any:
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default if k == path[-1] else None)
        if cur is None and k != path[-1]:
            return default
    return cur


def _set(d: dict, path: tuple[str, ...], value: Any) -> None:
    cur = d
    for k in path[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[path[-1]] = value


def _patch_file(path: Path, key_path: tuple[str, ...], value: Any) -> None:
    """Patch só o arquivo no disco (não dump do merge .env)."""
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}
    _set(data, key_path, value)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def settings_active(settings: dict, name: str) -> bool | None:
    path = ACTIVE_PATH.get(name)
    if not path:
        return None
    return bool(_get(settings, path, False))


def set_worker_active(
    settings: dict,
    runtime: Any,
    name: str,
    active: bool,
    *,
    file: Path | None = None,
    boot_active: set[str] | None = None,
    paused: list | None = None,
) -> str:
    path = ACTIVE_PATH.get(name)
    if not path:
        return f"{name}: sem Active no settings"

    _set(settings, path, bool(active))
    _patch_file(settings_file(file), path, bool(active))

    w = next((x for x in runtime.workers if x.name == name), None)
    if w is None:
        return f"{name}: Active={active} (sem worker)"

    # Brain.* exige Brain.Active no runtime
    eff = bool(active)
    if path[0] == "Brain" and len(path) > 2:
        eff = eff and bool((settings.get("Brain") or {}).get("Active"))

    if boot_active is not None:
        if eff:
            boot_active.add(name)
        else:
            boot_active.discard(name)

    if name in _SETTINGS_ONLY:
        return f"{name}: Active={active}"

    if paused is not None and w in paused:
        if not eff:
            paused.remove(w)
        w.active = False
        return f"{name}: Active={active} (pausado)"

    w.active = eff
    if eff:
        w._next_at = 0.0
        w.reason = "armed"
    else:
        w.reason = "off"
    return f"{name}: {'on' if active else 'off'}"


def toggle_worker(
    settings: dict,
    runtime: Any,
    name: str,
    **kw: Any,
) -> str:
    cur = settings_active(settings, name)
    if cur is None:
        return f"{name}: sem Active no settings"
    return set_worker_active(settings, runtime, name, not cur, **kw)


def toggle_at(
    settings: dict,
    runtime: Any,
    index: int,
    **kw: Any,
) -> str:
    workers = runtime.workers
    if index < 0 or index >= len(workers):
        return f"#{index_key(index)}: fora da lista"
    return toggle_worker(settings, runtime, workers[index].name, **kw)


def disable_all_for_vacation(
    settings: dict,
    runtime: Any,
    *,
    file: Path | None = None,
    boot_active: set[str] | None = None,
    paused: list | None = None,
) -> list[str]:
    """Desliga todos os workers + grava Active=false (1 write). Retorna nomes logáveis."""
    disk_path = settings_file(file)
    if disk_path.exists():
        disk = json.loads(disk_path.read_text(encoding="utf-8"))
        if not isinstance(disk, dict):
            disk = {}
    else:
        disk = {}

    changed: list[str] = []
    dirty = False
    for w in runtime.workers:
        path = ACTIVE_PATH.get(w.name)
        was_on = bool(w.active)
        if path:
            was_on = was_on or bool(_get(settings, path, False))
            _set(settings, path, False)
            _set(disk, path, False)
            dirty = True
        w.active = False
        w.reason = "off"
        if boot_active is not None:
            boot_active.discard(w.name)
        if paused is not None and w in paused:
            paused.remove(w)
        if was_on:
            changed.append(w.name)

    if dirty:
        disk_path.write_text(
            json.dumps(disk, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return changed


if __name__ == "__main__":
    assert key_to_index("1") == 0 and key_to_index("a") == 9
    assert key_to_index("b") is None and key_to_index("c") == 10
    assert key_to_index("v") is not None and key_to_index("b") is None
    assert index_key(0) == "1" and index_key(10) == "c"
    d: dict = {}
    _set(d, ("Brain", "AutoMine", "Active"), True)
    assert _get(d, ("Brain", "AutoMine", "Active")) is True
    tmp = ROOT / "_control_test_settings.json"
    try:
        tmp.write_text("{}", encoding="utf-8")
        _patch_file(tmp, ("Expeditions", "Active"), False)
        assert json.loads(tmp.read_text(encoding="utf-8"))["Expeditions"]["Active"] is False
    finally:
        tmp.unlink(missing_ok=True)

    class _W:
        def __init__(self, name: str, active: bool = True) -> None:
            self.name = name
            self.active = active
            self.reason = ""

    class _RT:
        def __init__(self, workers: list) -> None:
            self.workers = workers

    s2 = {"Expeditions": {"Active": True}, "Brain": {"AutoMine": {"Active": True}}}
    tmp2 = ROOT / "_control_vac_settings.json"
    try:
        tmp2.write_text(json.dumps(s2), encoding="utf-8")
        names = disable_all_for_vacation(
            s2, _RT([_W("Expeditions"), _W("AutoMine"), _W("Overview")]), file=tmp2
        )
        assert "Expeditions" in names and "AutoMine" in names and "Overview" in names
        assert s2["Expeditions"]["Active"] is False
        assert s2["Brain"]["AutoMine"]["Active"] is False
        disk2 = json.loads(tmp2.read_text(encoding="utf-8"))
        assert disk2["Expeditions"]["Active"] is False
    finally:
        tmp2.unlink(missing_ok=True)
    print("control ok")
