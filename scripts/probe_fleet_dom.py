"""Probe e2e: fleetdispatch DOM + ajax do updateTarget (não envia frota).

Uso (bot parado de preferência):
  .venv\\Scripts\\python.exe scripts\\probe_fleet_dom.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from config import load_settings
from game.browser import launch_browser, new_context, session_path
from game.fleet_ui import _install_ajax_hook, _snap, send_fleet_ui
from game.session import resume_session
from game.tech import open_component


def main() -> int:
    settings = load_settings()
    cred = settings["Credentials"]
    conf = cred.get("DeviceConf") or {}
    storage = session_path(conf)
    if not storage.exists():
        print(f"sem sessão: {storage}")
        return 1

    out = ROOT / "logs" / "fleet_probe.json"
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        ctx = new_context(browser, conf, storage_state=storage)
        page = ctx.new_page()
        game = resume_session(page, cred, log=lambda m, *_: print(m))
        if not game:
            print("resume falhou — rode o bot/login primeiro")
            browser.close()
            return 2
        page = game
        open_component(page, "fleetdispatch")
        _install_ajax_hook(page)
        boot = _snap(page)
        # 1 LC se houver; senão só snapshot
        ships = page.evaluate(
            """() => {
              const fd = window.fleetDispatcher;
              if (!fd || !fd.shipsOnPlanet) return {};
              for (const s of fd.shipsOnPlanet) {
                if (s.id === 203 && s.number > 0) return {203: 1};
              }
              for (const s of fd.shipsOnPlanet) {
                if (s.number > 0 && s.id !== 217) return {[s.id]: 1};
              }
              return {};
            }"""
        )
        cur = page.evaluate(
            """() => {
              const c = (window.fleetDispatcher || {}).currentPlanet || {};
              return {g: c.galaxy, s: c.system, p: c.position};
            }"""
        )
        print("planet", cur, "ships", ships)
        result = None
        if ships and cur.get("g"):
            # tenta UI completa (pode falhar no c3 — é o ponto)
            result = send_fleet_ui(
                page,
                {int(k): int(v) for k, v in ships.items()},
                int(cur["g"]),
                int(cur["s"]),
                16,
                mission=15,
                holding=1,
            )
        final = _snap(page)
        payload = {"boot": boot, "result": result, "final": final}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("result:", result)
        print("wrote", out)
        # resumo ajax
        for row in (final.get("ajaxLog") or [])[-5:]:
            print("ajax", row)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
