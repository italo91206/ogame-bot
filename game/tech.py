"""Technologies: parse, costs, build."""
from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.sync_api import Page

from .resources import parse_ogame_int

def open_component(page: Page, component: str) -> None:
    base = page.url.split("?")[0]
    m = re.search(r"[?&]cp=(\d+)", page.url)
    cp = f"&cp={m.group(1)}" if m else ""
    page.goto(
        f"{base}?page=ingame&component={component}{cp}",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("#resources_metal", timeout=30_000)


@dataclass
class Tech:
    id: int
    level: int
    status: str
    name: str = ""


def parse_technologies(page: Page) -> dict[int, Tech]:
    out: dict[int, Tech] = {}
    items = page.locator("li.technology[data-technology]")
    for i in range(items.count()):
        li = items.nth(i)
        tid_raw = li.get_attribute("data-technology") or ""
        if not tid_raw.isdigit():
            continue
        tid = int(tid_raw)
        status = li.get_attribute("data-status") or ""
        level = 0
        lvl = li.locator(".level[data-value], .amount[data-value]")
        if lvl.count():
            level = parse_ogame_int(lvl.first.get_attribute("data-value") or "0")
        out[tid] = Tech(tid, level, status, li.get_attribute("aria-label") or "")
    return out


def peek_tech_costs(page: Page, tech_id: int) -> dict[str, int] | None:
    """Open tech detail; read upgrade costs. Does not click Upgrade."""
    li = page.locator(f'li.technology[data-technology="{tech_id}"]')
    if not li.count():
        return None
    li.first.click()
    try:
        page.locator("div.costs").first.wait_for(state="visible", timeout=5_000)
    except Exception:
        return None
    costs: dict[str, int] = {}
    for key, cls in (("metal", "metal"), ("crystal", "crystal"), ("deut", "deuterium")):
        el = page.locator(f"div.costs li.{cls}")
        costs[key] = (
            parse_ogame_int(el.first.get_attribute("data-value") or "0") if el.count() else 0
        )
    return costs


def _build_fail_why(page: Page, tech_id: int, err: BaseException) -> str:
    """Short Playwright error + DOM snap for upgrade-click failures."""
    text = str(err)
    head = text.split("\n", 1)[0].strip()[:120]
    hints = [
        h
        for h in (
            "not visible",
            "not stable",
            "not enabled",
            "Timeout",
            "intercepts pointer",
            "outside of the viewport",
        )
        if h.lower() in text.lower()
    ]
    try:
        snap = page.evaluate(
            """(tid) => {
              const li = document.querySelector(
                `li.technology[data-technology="${tid}"]`
              );
              const btns = [...document.querySelectorAll("button.upgrade")].map(
                (b) => ({
                  t: b.getAttribute("data-technology"),
                  vis: b.getClientRects().length > 0,
                  dis: !!b.disabled,
                })
              );
              const comp =
                (location.search.match(/component=([^&]+)/) || [])[1] || "";
              return {
                status: li ? li.getAttribute("data-status") : null,
                costs: !!document.querySelector("div.costs"),
                btns,
                comp,
              };
            }""",
            str(tech_id),
        )
        return (
            f"{head}"
            + (f" [{', '.join(hints)}]" if hints else "")
            + f" | status={snap.get('status')} costs={snap.get('costs')}"
            + f" btns={snap.get('btns')} component={snap.get('comp')}"
        )
    except Exception:
        return head + (f" [{', '.join(hints)}]" if hints else "")


def _detail_open(page: Page, tech_id: int) -> bool:
    """True if tech detail panel is showing costs / upgrade for this id."""
    return bool(
        page.evaluate(
            """(tid) => {
              const costs = document.querySelector("div.costs");
              if (!costs) return false;
              const detail = document.querySelector(
                "#technologydetails, #technologyDetails, .technologydetails"
              );
              if (detail) {
                const t = detail.getAttribute("data-technology")
                  || detail.querySelector("[data-technology]")?.getAttribute("data-technology");
                if (t && t !== String(tid)) return false;
              }
              return !!document.querySelector(
                `button.upgrade[data-technology="${tid}"]`
              );
            }""",
            str(tech_id),
        )
    )


def _click_upgrade(page: Page, tech_id: int) -> None:
    """Click the detail-panel Upgrade (not the list icon under the overlay)."""
    # shipyard/supplies keep 2× button.upgrade; grid .first is covered → intercepts pointer
    ok = page.evaluate(
        """(tid) => {
          const sel = `button.upgrade[data-technology="${tid}"]`;
          const roots = [
            document.querySelector("#technologydetails"),
            document.querySelector("#technologyDetails"),
            document.querySelector(".technologydetails"),
            document.querySelector("div.costs")?.closest("div"),
          ].filter(Boolean);
          for (const root of roots) {
            const b = root.querySelector(sel);
            if (b && !b.disabled) { b.click(); return true; }
          }
          const vis = [...document.querySelectorAll(sel)].filter(
            (b) => !b.disabled && b.getClientRects().length > 0
          );
          if (!vis.length) return false;
          vis[vis.length - 1].click();
          return true;
        }""",
        str(tech_id),
    )
    if not ok:
        raise RuntimeError(f"upgrade btn tech={tech_id} ausente")


def build_technology(page: Page, tech_id: int) -> str | None:
    """Click tech → Upgrade. None=ok, else short fail reason for logs."""
    li = page.locator(f'li.technology[data-technology="{tech_id}"]')
    if not li.count():
        return f"li tech={tech_id} ausente"
    status = li.first.get_attribute("data-status") or "?"
    if status != "on":
        return f"data-status={status} (esperado on)"
    try:
        if not _detail_open(page, tech_id):
            li.first.click(timeout=8_000)
            page.locator("div.costs").first.wait_for(state="visible", timeout=5_000)
        _click_upgrade(page, tech_id)
    except Exception as e:
        return _build_fail_why(page, tech_id, e)
    page.wait_for_timeout(1200)
    return None


def build_ships(page: Page, tech_id: int, amount: int) -> str | None:
    """Shipyard: set amount + build. None=ok."""
    n = max(1, int(amount))
    open_component(page, "shipyard")
    li = page.locator(f'li.technology[data-technology="{tech_id}"]')
    if not li.count():
        return f"li tech={tech_id} ausente"
    status = li.first.get_attribute("data-status") or "?"
    if status != "on":
        return f"data-status={status} (esperado on)"
    try:
        li.first.click(timeout=8_000)
        page.locator("div.costs").first.wait_for(state="visible", timeout=5_000)
        filled = page.evaluate(
            """(n) => {
              const el = document.querySelector(
                'input#build_amount, input[name="amount"], input.amount, '
                + '.technologydetails input, #technologydetails input'
              );
              if (!el) return false;
              el.focus();
              el.value = String(n);
              el.dispatchEvent(new Event('input', {bubbles: true}));
              el.dispatchEvent(new Event('change', {bubbles: true}));
              return true;
            }""",
            n,
        )
        if not filled:
            inp = page.locator(
                'input#build_amount, input[name="amount"], input.amount'
            )
            if inp.count():
                inp.first.fill(str(n))
        _click_upgrade(page, tech_id)
    except Exception as e:
        return _build_fail_why(page, tech_id, e)
    page.wait_for_timeout(1200)
    return None
