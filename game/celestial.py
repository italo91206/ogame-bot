"""Parse / switch planets and fleet slots."""
from __future__ import annotations

import re

from playwright.sync_api import Page

from . import dom_health
from .models import Celestial, Coords, FleetSlots
from .resources import current_resources, resource_production_per_hour

_COORDS_RE = re.compile(r"\[?\s*(\d+)\s*:\s*(\d+)\s*:\s*(\d+)\s*\]?")


def parse_celestials(page: Page) -> list[Celestial]:
    """Parse #planetList → planets + moons."""
    out: list[Celestial] = []
    planets = page.locator("#planetList .smallplanet")
    n = planets.count()
    for i in range(n):
        node = planets.nth(i)
        pid = (node.get_attribute("id") or "").replace("planet-", "") or str(i)
        try:
            name = node.locator(".planet-name").first.inner_text(timeout=1000).strip()
        except Exception:
            name = f"P{i+1}"
        try:
            raw = node.locator(".planet-koords, .planet-coords, .coords").first.inner_text(timeout=1000)
        except Exception:
            raw = ""
        m = _COORDS_RE.search(raw) or _COORDS_RE.search(node.inner_text())
        if not m:
            continue
        g, s, p = map(int, m.groups())
        try:
            href = node.locator("a.planetlink").first.get_attribute("href") or ""
            cpm = re.search(r"cp=(\d+)", href)
            if cpm:
                pid = cpm.group(1)
        except Exception:
            pass
        out.append(Celestial(id=pid, name=name, coords=Coords(g, s, p, "Planet")))

        moon = node.locator("a.moonlink")
        if moon.count():
            href = moon.first.get_attribute("href") or ""
            mid = re.search(r"cp=(\d+)", href)
            out.append(
                Celestial(
                    id=mid.group(1) if mid else f"{pid}-moon",
                    name=f"{name} Moon",
                    coords=Coords(g, s, p, "Moon"),
                )
            )
    if out:
        dom_health.mark_good()
    return out


def switch_celestial(page: Page, target: Celestial | Coords) -> None:
    if isinstance(target, Celestial):
        cp = target.id
        # prefer clicking planet/moon link
        sel = (
            f'a.moonlink[href*="cp={cp}"]'
            if target.coords.type == "Moon"
            else f'a.planetlink[href*="cp={cp}"]'
        )
        loc = page.locator(sel)
        if loc.count():
            loc.first.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_selector("#resources_metal", timeout=30_000)
            return
        coords = target.coords
    else:
        coords = target
        cp = None

    # fallback: match by coords text
    needle = f"[{coords.galaxy}:{coords.system}:{coords.position}]"
    row = page.locator("#planetList .smallplanet").filter(has_text=needle)
    if not row.count():
        raise RuntimeError(f"celestial {coords} não encontrado")
    link = row.first.locator("a.moonlink" if coords.type == "Moon" else "a.planetlink")
    if not link.count():
        raise RuntimeError(f"link {coords.type} ausente em {coords}")
    link.first.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_selector("#resources_metal", timeout=30_000)


def scan_all_resources(
    page: Page,
) -> list[tuple[Celestial, dict[str, str], dict[str, int]]]:
    """Switch each celestial, read resources + prod/h, restore starting one."""
    celestials = parse_celestials(page)
    if not celestials:
        return []
    start = celestials[0]
    # try keep current planet: first with .active / highlight
    try:
        active = page.locator(
            "#planetList .smallplanet.active, #planetList .smallplanet.hightlightPlanet"
        ).first
        if active.count():
            href = active.locator("a.planetlink").first.get_attribute("href") or ""
            m = re.search(r"cp=(\d+)", href)
            if m:
                start = next((c for c in celestials if c.id == m.group(1)), start)
    except Exception:
        pass

    out: list[tuple[Celestial, dict[str, str], dict[str, int]]] = []
    for c in celestials:
        switch_celestial(page, c)
        out.append((c, current_resources(page), resource_production_per_hour(page)))
    if out and out[-1][0].id != start.id:
        switch_celestial(page, start)
    return out


def parse_slots(page: Page) -> FleetSlots:
    """Fleet + expedition slots from #slots / movement / overview."""
    html = page.content()
    # fleetdispatch: <div id="slots"> fleets used/total · expos used/total
    m = re.search(
        r'id="slots"[^>]*>.*?(\d+)\s*/\s*(\d+).*?(\d+)\s*/\s*(\d+)',
        html,
        re.I | re.S,
    )
    if m:
        fu, ft, eu, et = map(int, m.groups())
        return FleetSlots(free=max(0, ft - fu), total=ft, exp_free=max(0, et - eu), exp_total=et)
    m = re.search(
        r'fleetSlots[^>]*>.*?(\d+).*?(\d+).*?expSlots[^>]*>.*?(\d+).*?(\d+)',
        html,
        re.I | re.S,
    )
    if m:
        fu, ft, eu, et = map(int, m.groups())
        return FleetSlots(free=max(0, ft - fu), total=ft, exp_free=max(0, et - eu), exp_total=et)
    for pat in (
        r'id="slots"[^>]*>.*?(\d+)\s*/\s*(\d+)',
        r'fleetSlots[^>]*>.*?(\d+)\s*/\s*(\d+)',
        r'(?:Fleets|Frotas)\s*[:=]?\s*(\d+)\s*/\s*(\d+)',
    ):
        m = re.search(pat, html, re.I | re.S)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b:
                return FleetSlots(free=b - a, total=b)
            return FleetSlots(free=a, total=b)
    return FleetSlots(free=0, total=0)


def fleet_slots(page: Page) -> FleetSlots:
    """Slots for send gates. #slots is missing on research/supplies → 0/0 false 'sem slot'."""
    s = parse_slots(page)
    if s.total > 0:
        return s
    from .tech import open_component

    open_component(page, "fleetdispatch")
    return parse_slots(page)
