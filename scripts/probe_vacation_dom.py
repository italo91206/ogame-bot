"""Dump #advice-bar / vacation markers from live session."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from config import load_settings
from game.browser import launch_browser, new_context, session_path
from game.session import resume_session
from game.vacation import href_is_vacation, is_vacation_mode


def main() -> int:
    settings = load_settings()
    cred = settings["Credentials"]
    conf = cred.get("DeviceConf") or {}
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        ctx = new_context(browser, conf, storage_state=session_path(conf))
        page = ctx.new_page()
        game = resume_session(page, cred, log=lambda m, lv="info": print(f"[{lv}] {m}"))
        if not game:
            print("resume fail")
            return 2
        page = game
        snap = page.evaluate(
            """() => {
              const bar = document.querySelector('#advice-bar')
                || document.querySelector('#adviceBar');
              const links = [...document.querySelectorAll(
                '#advice-bar a, #adviceBar a, a[href*="preferences"], a[href*="selectedTab"]'
              )];
              const body = document.body ? document.body.innerText : '';
              return {
                url: location.href,
                hasBar: !!bar,
                barHtml: bar ? bar.outerHTML.slice(0, 2000) : null,
                hrefs: links.map(a => a.getAttribute('href')),
                texts: links.map(a => (a.textContent || '').trim().slice(0, 100)),
                bodyClass: document.body ? document.body.className : '',
                vacHit: (body.match(/modo de f[eé]rias|vacation mode|urlaubsmodus/i) || [null])[0],
              };
            }"""
        )
        print(json.dumps(snap, indent=2, ensure_ascii=False))
        print("href_is_vacation:", [href_is_vacation(h or "") for h in (snap.get("hrefs") or [])])
        print("is_vacation_mode:", is_vacation_mode(page))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
