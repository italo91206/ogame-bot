"""Confirm overview request embeds hostiles while eventList AJAX is empty."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from config import load_settings
from game.attacks import parse_hostile_attacks_html
from game.browser import launch_browser, new_context, session_path
from game.session import resume_session


def main() -> int:
    settings = load_settings()
    cred = settings["Credentials"]
    conf = cred.get("DeviceConf") or {}
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        ctx = new_context(browser, conf, storage_state=session_path(conf))
        page = ctx.new_page()
        game = resume_session(page, cred, log=lambda *_: None)
        page = game
        base = page.url.split("?")[0]
        hdr = {"X-Requested-With": "XMLHttpRequest"}

        ajax = page.request.get(
            f"{base}?page=componentOnly&component=eventList&ajax=1", headers=hdr
        ).text() or ""
        overview = page.request.get(
            f"{base}?page=ingame&component=overview"
        ).text() or ""
        eventlist_page = page.request.get(
            f"{base}?page=ingame&component=eventlist"
        ).text() or ""

        for name, html in (
            ("ajax", ajax),
            ("overview_req", overview),
            ("eventlist_page", eventlist_page),
        ):
            atks = parse_hostile_attacks_html(html)
            print(
                f"{name}: bytes={len(html)} fleets={html.count('eventFleet')} "
                f"parsed={len(atks)}"
            )
            for a in atks[:3]:
                print(f"  {a.attacker_name} → {a.dest} m={a.mission} in={a.arrive_in:.0f}s")
        print("page still at", page.url[:80])
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
