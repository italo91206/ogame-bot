"""Load .env + settings.json. Secrets stay in .env."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_SETTINGS = ROOT / "settings.json"

_DEFAULTS: dict[str, Any] = {
    "Credentials": {
        "Universe": "",
        "Email": "",
        "Password": "",
        "Language": "br",
        "Lobby": "lobby",
        "LobbyPioneers": False,
        "DeviceConf": {
            "Name": "Device-name",
            "System": "Windows",
            "Browser": "Chrome",
            "UserAgent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Memory": 8,
            "Concurrency": 16,
            "Color": 24,
            "Width": 1920,
            "Height": 1080,
            "Timezone": "America/Sao_Paulo",
            "Lang": "pt-BR",
        },
    },
    "General": {
        "SlotsToLeaveFree": 1,
        "CaptchaAPIKey": "",
        "Headless": False,
    },
}


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        # .env wins (Windows LANG=en_US.UTF-8 must not block LANG=br)
        os.environ[k.strip()] = v.strip()


def community_lang(raw: str | None, default: str = "br") -> str:
    """OGame community code (br/us/…), not OS locale (en_US.UTF-8)."""
    v = (raw or default).strip().lower()
    if not v:
        return default
    if "." in v:  # en_us.utf-8
        v = v.split(".", 1)[0]
    if "_" in v or "-" in v:  # en_us / pt-br
        loc = v.replace("-", "_")
        return {"pt_br": "br", "pt_pt": "pt", "en_us": "us", "en_gb": "en"}.get(
            loc, default
        )
    return v


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(path: Path | None = None) -> dict[str, Any]:
    load_env()
    path = path or Path(os.environ.get("SETTINGS_PATH", DEFAULT_SETTINGS))
    data = dict(_DEFAULTS)
    if path.exists():
        data = _deep_merge(data, json.loads(path.read_text(encoding="utf-8")))

    cred = data["Credentials"]
    # .env wins for secrets / universe
    if os.environ.get("EMAIL"):
        cred["Email"] = os.environ["EMAIL"]
    if os.environ.get("PASSWORD"):
        cred["Password"] = os.environ["PASSWORD"]
    if os.environ.get("UNIVERSE"):
        cred["Universe"] = os.environ["UNIVERSE"]
    if os.environ.get("LANG"):
        cred["Language"] = community_lang(os.environ["LANG"])
    else:
        cred["Language"] = community_lang(cred.get("Language"))
    if os.environ.get("LOBBY"):
        cred["Lobby"] = os.environ["LOBBY"]
    if os.environ.get("CAPTCHA_API_KEY"):
        data["General"]["CaptchaAPIKey"] = os.environ["CAPTCHA_API_KEY"]
    if os.environ.get("HEADLESS") is not None:
        data["General"]["Headless"] = os.environ["HEADLESS"].strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    missing = [k for k in ("Email", "Password", "Universe") if not cred.get(k)]
    if missing:
        sys.exit(f"Falta credencial: {', '.join(missing)} (.env ou settings.json)")
    return data


def reload_settings(path: Path | None = None) -> dict[str, Any]:
    """Re-read JSON (hot-reload manual). Env already loaded."""
    return load_settings(path)


if __name__ == "__main__":
    # self-check sem .env real: só merge
    s = _deep_merge(_DEFAULTS, {"General": {"SlotsToLeaveFree": 2}})
    assert s["General"]["SlotsToLeaveFree"] == 2
    assert s["Credentials"]["DeviceConf"]["Width"] == 1920
    assert community_lang("br") == "br"
    assert community_lang("en_US.UTF-8") == "us"
    assert community_lang("pt_BR") == "br"
    print("config ok")
