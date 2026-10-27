"""Focus = perfis nomeados de Active (pacote on/off). Sem DOM."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from control import (
    ACTIVE_PATH,
    draft_active,
    set_worker_active,
    settings_active,
    settings_file,
    _set,
)

# masters fora de ACTIVE_PATH (não são Worker.name)
MASTER_PATH: dict[str, tuple[str, ...]] = {
    "Brain": ("Brain", "Active"),
    "Transports": ("Brain", "Transports", "Active"),
}

_KEYS = (
    "SleepMode",
    "Defender",
    "Expeditions",
    "AutoFarm",
    "AutoHarvest",
    "AutoColonize",
    "AutoDiscovery",
    "Brain",
    "Transports",
    "AutoMine",
    "AutoResearch",
    "LifeformAutoMine",
    "LifeformAutoResearch",
    "AutoCargo",
    "AutoRepatriate",
)


def _pack(**on: bool) -> dict[str, bool]:
    base = {k: False for k in _KEYS}
    base.update(on)
    return base


# padrão TBot: economia + frota; Sleep/Harvest off
GERAL = _pack(
    Defender=True,
    Expeditions=True,
    AutoFarm=True,
    AutoColonize=True,
    AutoDiscovery=True,
    Brain=True,
    Transports=True,
    AutoMine=True,
    AutoResearch=True,
    LifeformAutoMine=True,
    LifeformAutoResearch=True,
    AutoCargo=True,
    AutoRepatriate=True,
)

# só frota de rotina: fleetsave (SleepMode) + Defender + Expo
EXPEDITIONS = _pack(
    SleepMode=True,
    Defender=True,
    Expeditions=True,
)

BUILTIN: dict[str, dict[str, bool]] = {
    "geral": GERAL,
    "expeditions": EXPEDITIONS,
}
# alias legado
ALIASES: dict[str, str] = {"general": "geral"}

# compat exports
GENERAL = GERAL

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")
_DEFAULT = "geral"


def _resolve_name(name: str) -> str:
    n = (name or "").strip().lower()
    return ALIASES.get(n, n)


def _focus_block(settings: dict) -> dict:
    f = settings.get("Focus")
    if not isinstance(f, dict):
        f = {}
        settings["Focus"] = f
    cur = _resolve_name(str(f.get("Current") or _DEFAULT))
    f["Current"] = cur if cur in BUILTIN or cur in (f.get("Profiles") or {}) else _DEFAULT
    f["Default"] = _resolve_name(str(f.get("Default") or _DEFAULT)) or _DEFAULT
    profiles = f.get("Profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        f["Profiles"] = profiles
    for name, pack in BUILTIN.items():
        if name not in profiles:
            profiles[name] = dict(pack)
    # migrate legado general → geral
    if "general" in profiles and "geral" in profiles:
        profiles.pop("general", None)
    return f


def current_name(settings: dict) -> str:
    return str(_focus_block(settings).get("Current") or _DEFAULT)


def list_profiles(settings: dict) -> list[str]:
    f = _focus_block(settings)
    names = set(f["Profiles"]) | set(BUILTIN)
    names.discard("general")
    ordered = [n for n in ("geral", "expeditions") if n in names]
    ordered += sorted(n for n in names if n not in ordered)
    return ordered


def validate_name(name: str) -> str | None:
    n = (name or "").strip().lower()
    if not _NAME_RE.match(n):
        return None
    return n


def snapshot(
    settings: dict,
    draft: dict[str, bool] | None = None,
) -> dict[str, bool]:
    """Actives atuais (rascunho ∪ settings) + Brain/Transports."""
    out: dict[str, bool] = {}
    for name in ACTIVE_PATH:
        if draft is not None:
            v = draft_active(draft, settings, name)
        else:
            v = settings_active(settings, name)
        out[name] = bool(v) if v is not None else False
    out["Brain"] = any(
        out.get(n) for n, p in ACTIVE_PATH.items() if p[0] == "Brain"
    )
    out["Transports"] = bool(
        ((settings.get("Brain") or {}).get("Transports") or {}).get("Active")
    )
    return out


def profile_actives(settings: dict, name: str) -> dict[str, bool] | None:
    n = _resolve_name(validate_name(name) or (name or "").strip().lower())
    if n in BUILTIN:
        stored = (_focus_block(settings).get("Profiles") or {}).get(n)
        base = dict(BUILTIN[n])
        if isinstance(stored, dict) and stored:
            base.update({k: bool(v) for k, v in stored.items() if k in base})
        return base
    raw = (_focus_block(settings).get("Profiles") or {}).get(n)
    if not isinstance(raw, dict):
        return None
    base = {k: False for k in _KEYS}
    base.update({k: bool(v) for k, v in raw.items() if k in _KEYS})
    return base


def _persist_focus_and_actives(
    settings: dict,
    actives: dict[str, bool],
    *,
    file: Path | None = None,
) -> None:
    disk_path = settings_file(file)
    if disk_path.exists():
        data = json.loads(disk_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    else:
        data = {}
    for name, on in actives.items():
        path = ACTIVE_PATH.get(name) or MASTER_PATH.get(name)
        if path:
            _set(settings, path, bool(on))
            _set(data, path, bool(on))
    f = _focus_block(settings)
    data["Focus"] = {
        "Current": f.get("Current", _DEFAULT),
        "Default": f.get("Default", _DEFAULT),
        "Profiles": f.get("Profiles") or {},
    }
    disk_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def save_profile(
    settings: dict,
    name: str,
    actives: dict[str, bool] | None = None,
    *,
    file: Path | None = None,
) -> str:
    n = validate_name(name)
    if not n:
        return "perfil: nome inválido (a-z, 0-9, _-, máx 24)"
    n = _resolve_name(n)
    snap = dict(actives) if actives is not None else snapshot(settings)
    pack = {k: bool(snap.get(k, False)) for k in _KEYS}
    f = _focus_block(settings)
    f["Profiles"][n] = pack
    f["Current"] = n
    _persist_focus_and_actives(settings, {}, file=file)
    return f"perfil '{n}' salvo"


def apply_profile(
    settings: dict,
    runtime: Any,
    name: str,
    *,
    file: Path | None = None,
    boot_active: set[str] | None = None,
    paused: list | None = None,
) -> list[str]:
    n = _resolve_name(validate_name(name) or (name or "").strip().lower())
    actives = profile_actives(settings, n)
    if actives is None:
        return [f"perfil '{name}': não existe"]
    f = _focus_block(settings)
    f["Current"] = n
    if n in BUILTIN and n not in (f.get("Profiles") or {}):
        f["Profiles"][n] = dict(BUILTIN[n])

    msgs: list[str] = []
    for master in ("Brain", "Transports"):
        path = MASTER_PATH[master]
        on = bool(actives.get(master, False))
        _set(settings, path, on)
        msgs.append(f"{master}: {'on' if on else 'off'}")

    for wname in ACTIVE_PATH:
        on = bool(actives.get(wname, False))
        msgs.append(
            set_worker_active(
                settings,
                runtime,
                wname,
                on,
                persist=False,
                boot_active=boot_active,
                paused=paused,
            )
        )
    _persist_focus_and_actives(settings, actives, file=file)
    return msgs


def cycle_profile(settings: dict, *, delta: int = 1) -> str:
    names = list_profiles(settings)
    cur = current_name(settings)
    try:
        i = names.index(cur)
    except ValueError:
        i = 0
    return names[(i + delta) % len(names)]


if __name__ == "__main__":
    assert validate_name("geral") == "geral"
    assert _resolve_name("general") == "geral"
    assert GERAL["Defender"] and GERAL["Brain"] and not GERAL["SleepMode"]
    assert EXPEDITIONS["SleepMode"] and EXPEDITIONS["Expeditions"]
    assert not EXPEDITIONS["Brain"] and not EXPEDITIONS["AutoMine"]
    s: dict = {"Brain": {"Active": False, "AutoMine": {"Active": False}}}
    assert profile_actives(s, "geral")["AutoMine"] is True
    assert profile_actives(s, "general")["AutoMine"] is True
    assert profile_actives(s, "expeditions")["SleepMode"] is True
    assert profile_actives(s, "expeditions")["AutoMine"] is False
    from control import ROOT

    class _W:
        def __init__(self, name: str) -> None:
            self.name = name
            self.active = False
            self.reason = ""
            self._next_at = 0.0

    class _RT:
        def __init__(self) -> None:
            self.workers = [_W(n) for n in ACTIVE_PATH]

    tmp = ROOT / "_focus_test_settings.json"
    try:
        tmp.write_text("{}", encoding="utf-8")
        st: dict = {
            "Brain": {
                "Active": True,
                "AutoMine": {"Active": True},
                "Transports": {"Active": True},
            }
        }
        rt = _RT()
        apply_profile(st, rt, "expeditions", file=tmp)
        assert st["Brain"]["Active"] is False
        assert st["Expeditions"]["Active"] is True
        assert st["SleepMode"]["Active"] is True
        assert st["Defender"]["Active"] is True
        disk = json.loads(tmp.read_text(encoding="utf-8"))
        assert disk["Focus"]["Current"] == "expeditions"
        assert "geral" in disk["Focus"]["Profiles"]
        apply_profile(st, rt, "geral", file=tmp)
        assert st["Brain"]["Active"] is True
        assert list_profiles(st)[:2] == ["geral", "expeditions"]
    finally:
        tmp.unlink(missing_ok=True)
    print("focus ok")
