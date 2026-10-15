"""Discover how hostile fleets appear in DOM vs AJAX."""
from __future__ import annotations

import json
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
        game = resume_session(page, cred, log=lambda m, *_: print("log:", m))
        page = game

        def snap(label: str) -> None:
            info = page.evaluate(
                """() => {
                  const rows = [...document.querySelectorAll('tr.eventFleet, tr.allianceAttack')];
                  const alert = document.querySelector('#attack_alert');
                  const hostile = rows.filter(r =>
                    r.querySelector('.hostile, td.countDown.hostile')
                  ).map(r => ({
                    id: r.id,
                    mission: r.getAttribute('data-mission-type'),
                    html: r.outerHTML.slice(0, 200),
                  }));
                  return {
                    url: location.href.slice(0, 100),
                    rows: rows.length,
                    hostile: hostile.length,
                    alert: alert ? {
                      className: alert.className,
                      title: alert.getAttribute('data-tooltip-title') || '',
                    } : null,
                    sample: hostile[0] || null,
                  };
                }"""
            )
            print(f"\n[{label}]", json.dumps(info, ensure_ascii=False)[:800])
            html = page.content()
            atks = parse_hostile_attacks_html(html)
            print(f"  parsed_from_content={len(atks)}")
            for a in atks[:3]:
                print(f"  -> {a.attacker_name} {a.dest} in={a.arrive_in:.0f}s")

        snap("after_resume")

        # try game helpers
        helpers = page.evaluate(
            """() => ({
              toggleEvents: typeof toggleEvents,
              getAjaxEventbox: typeof getAjaxEventbox,
              refreshFleetEvents: typeof refreshFleetEvents,
              fetchEventbox: typeof fetchEventbox,
            })"""
        )
        print("helpers", helpers)

        page.evaluate(
            """() => {
              try { if (typeof toggleEvents === 'function') toggleEvents(); } catch (e) {}
              const a = document.querySelector('#attack_alert a, #attack_alert');
              if (a) a.click();
            }"""
        )
        page.wait_for_timeout(1500)
        snap("after_toggle")

        fetched = page.evaluate(
            """async () => {
              const base = location.href.split('?')[0];
              const urls = [
                '?page=componentOnly&component=eventList&ajax=1',
                '?page=eventList&ajax=1',
                '?page=fetchEventbox&ajax=1',
              ];
              const out = [];
              for (const q of urls) {
                try {
                  const r = await fetch(base + q, {
                    headers: {'X-Requested-With': 'XMLHttpRequest'},
                    credentials: 'same-origin',
                  });
                  const t = await r.text();
                  out.push({
                    q,
                    status: r.status,
                    len: t.length,
                    fleets: (t.match(/eventFleet/g) || []).length,
                    hostile: (t.match(/hostile/g) || []).length,
                    head: t.slice(0, 160).replace(/\\s+/g, ' '),
                  });
                } catch (e) {
                  out.push({q, err: String(e)});
                }
              }
              return out;
            }"""
        )
        print("fetch", json.dumps(fetched, ensure_ascii=False, indent=2)[:2000])

        # force reload overview and wait for network
        base = page.url.split("?")[0]
        with page.expect_response(
            lambda r: "eventList" in r.url or "fetchEventbox" in r.url or "eventbox" in r.url.lower(),
            timeout=8000,
        ) as _resp:
            page.goto(
                f"{base}?page=ingame&component=overview",
                wait_until="domcontentloaded",
                timeout=30000,
            )
        try:
            resp = _resp.value
            body = resp.text()
            print(
                f"\ncaptured {resp.url[-80:]} status={resp.status} "
                f"fleets={(body or '').count('eventFleet')} len={len(body or '')}"
            )
            print((body or "")[:300].replace("\n", " "))
        except Exception as e:
            print("no event response", e)
        page.wait_for_timeout(2000)
        snap("after_overview_reload")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
