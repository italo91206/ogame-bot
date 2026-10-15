"""Probe fetchEventbox + attack_alert vs empty eventList."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from config import load_settings
from game.browser import launch_browser, new_context, session_path
from game.session import resume_session


def main() -> int:
    settings = load_settings()
    cred = settings["Credentials"]
    conf = cred.get("DeviceConf") or {}
    storage = session_path(conf)

    with sync_playwright() as p:
        browser = launch_browser(p, headless=True)
        ctx = new_context(browser, conf, storage_state=storage)
        page = ctx.new_page()
        game = resume_session(page, cred, log=lambda *_: None)
        if not game:
            print("resume fail")
            return 2
        page = game
        base = page.url.split("?")[0]

        candidates = [
            "?page=fetchEventbox&ajax=1",
            "?page=componentOnly&component=fetchEventbox&ajax=1",
            "?page=componentOnly&component=eventList&ajax=1",
            "?page=componentOnly&component=eventList&action=fetchEventBox&ajax=1",
        ]
        for q in candidates:
            url = base + q
            resp = page.request.get(
                url,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
            )
            text = resp.text() or ""
            ct = resp.headers.get("content-type", "")
            preview = text[:220].replace("\n", " ")
            print(f"\n{q}")
            print(f"  status={resp.status} ct={ct[:50]} len={len(text)}")
            print(f"  body={preview!r}")
            if text.strip().startswith("{"):
                try:
                    data = json.loads(text)
                    print(f"  keys={list(data)[:20]}")
                    for k in ("hostile", "Hostile", "neutral", "Neutral", "friendly", "Friendly"):
                        if k in data:
                            print(f"  {k}={data[k]}")
                except json.JSONDecodeError:
                    pass

        # browser-side fetch (same cookies as page)
        box = page.evaluate(
            """async () => {
              const base = location.href.split('?')[0];
              const urls = [
                base + '?page=fetchEventbox&ajax=1',
                base + '?page=componentOnly&component=fetchEventbox&ajax=1',
              ];
              const out = [];
              for (const u of urls) {
                const r = await fetch(u, {
                  headers: {'X-Requested-With': 'XMLHttpRequest'},
                  credentials: 'same-origin',
                });
                const txt = await r.text();
                out.push({q: u.split('?')[1], status: r.status, txt: txt.slice(0, 300)});
              }
              const a = document.querySelector('#attack_alert');
              out.push({
                alert: a ? {
                  className: a.className,
                  title: a.getAttribute('data-tooltip-title') || '',
                } : null,
              });
              return out;
            }"""
        )
        print("\nEVAL", json.dumps(box, ensure_ascii=False, indent=2)[:2500])

        html = page.content()
        (ROOT / "logs" / "overview_probe.html").write_text(html, encoding="utf-8")
        print("\ncounts", {k: len(re.findall(k, html, re.I)) for k in (
            "attack_alert", "eventFleet", "hostile", "soon", "today"
        )})
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
