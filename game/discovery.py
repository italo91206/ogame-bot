"""Lifeform Discovery fleet (mission 18 / sendDiscoveryFleet)."""
from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

from .fleet_ajax import _debug_dump, _err_bits, _fleet_post
from .galaxy import _galaxy_raw


def _galaxy_token(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    return str(data.get("token") or "").strip()


def send_discovery(page: Page, galaxy: int, system: int, position: int) -> str:
    """POST sendDiscoveryFleet. Token from fetchGalaxyContent (ogamed parity)."""
    g, s, p = int(galaxy), int(system), int(position)
    data, _text = _galaxy_raw(page, g, s)
    token = _galaxy_token(data)
    if not token:
        _debug_dump("discovery_no_token", {"g": g, "s": s, "p": p, "url": page.url[-120:]})
        return "fail: sem token (galaxy)"
    form = {
        "token": token,
        "galaxy": str(g),
        "system": str(s),
        "position": str(p),
    }
    res = _fleet_post(page, "sendDiscoveryFleet", form)
    inner = res.get("response") if isinstance(res.get("response"), dict) else res
    if isinstance(inner, dict) and inner.get("success"):
        return "ok"
    msg = ""
    if isinstance(inner, dict):
        msg = str(inner.get("message") or "")
    if not msg:
        msg = _err_bits(res)
    _debug_dump(
        "discovery_fail",
        {
            "form": {k: v for k, v in form.items() if k != "token"},
            "response": {
                k: v
                for k, v in res.items()
                if k not in ("fleetSendingToken", "newAjaxToken", "components")
            },
        },
    )
    return f"fail: {msg}"


if __name__ == "__main__":
    assert _galaxy_token(None) == ""
    assert _galaxy_token({"token": "abc"}) == "abc"
    print("discovery ok")
