"""Dump eventList AJAX + parse hostis (bot preferencialmente rodando ok).

  .venv\\Scripts\\python.exe scripts\\probe_eventlist.py
"""
from __future__ import annotations

import re
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
    storage = session_path(conf)
    if not storage.exists():
        print(f"sem sessão: {storage}")
        return 1

    out = ROOT / "logs" / "eventlist_probe.html"
    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        ctx = new_context(browser, conf, storage_state=storage)
        page = ctx.new_page()
        game = resume_session(page, cred, log=lambda m, *_: print(m))
        if not game:
            print("resume falhou")
            browser.close()
            return 2
        page = game
        base = page.url.split("?")[0]
        urls = [
            f"{base}?page=componentOnly&component=eventList&ajax=1",
            f"{base}?page=eventList&ajax=1",
        ]
        for i, url in enumerate(urls):
            resp = page.request.get(
                url, headers={"X-Requested-With": "XMLHttpRequest"}
            )
            html = resp.text() or ""
            path = out if i == 0 else out.with_name(f"eventlist_probe_{i}.html")
            path.write_text(html, encoding="utf-8")
            wrap = "eventListWrap" in html
            rows = len(re.findall(r'class="[^"]*eventFleet', html, re.I))
            hostile = len(
                re.findall(r'countDown[^"]*hostile|class="[^"]*hostile', html, re.I)
            )
            atks = parse_hostile_attacks_html(html)
            print(f"--- url[{i}] status={resp.status} bytes={len(html)}")
            print(f"    wrap={wrap} eventFleet={rows} hostile_hits={hostile} parsed={len(atks)}")
            print(f"    page.url={page.url[:120]}")
            for a in atks[:8]:
                print(
                    f"    atk id={a.id} m={a.mission} {a.attacker_name} "
                    f"→ {a.dest} in={a.arrive_in:.0f}s ships={a.ships}"
                )
            if not atks and rows:
                # sample first row snippet
                m = re.search(
                    r'<tr[^>]*class="[^"]*eventFleet[^"]*"[^>]*>.*?</tr>',
                    html,
                    re.I | re.S,
                )
                if m:
                    snip = re.sub(r"\s+", " ", m.group(0))[:400]
                    print(f"    sample_row: {snip}")
        # also check attack_alert on overview DOM
        alert = page.evaluate(
            """() => {
              const a = document.querySelector('#attack_alert, .attack_alert, #eventboxAttack');
              if (!a) return {found:false};
              return {
                found: true,
                id: a.id || '',
                class: a.className || '',
                text: (a.textContent || '').trim().slice(0,120),
                html: a.outerHTML.slice(0,300),
              };
            }"""
        )
        print(f"--- attack_alert DOM: {alert}")
        browser.close()
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
