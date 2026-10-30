"""Shared eventList: AJAX fetch + DOM/refresh + HTML row helpers (I-01 / I-02)."""
from __future__ import annotations

import re
import time

from playwright.sync_api import Page

from .fleet_dispatch import MISSION_DISCOVERY, MISSION_EXPEDITION

_COORDS_RE = re.compile(r"\[(\d+):(\d+):(\d+)\]")
_EVENT_FLEET_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*eventFleet[^"]*"[^>]*>.*?</tr>',
    re.I | re.S,
)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def fetch_event_list_html(page: Page) -> str:
    """AJAX `component=eventList`. Empty string on hard fail."""
    base = page.url.split("?")[0]
    url = f"{base}?page=componentOnly&component=eventList&ajax=1"
    try:
        return (
            page.request.get(
                url, headers={"X-Requested-With": "XMLHttpRequest"}
            ).text()
            or ""
        )
    except Exception:
        return ""


def dom_event_rows_html(page: Page) -> str:
    """tr.eventFleet / allianceAttack já no DOM (overview SSR / eventbox)."""
    try:
        return (
            page.evaluate(
                """() => {
                  const rows = [...document.querySelectorAll(
                    'tr.eventFleet, tr.allianceAttack'
                  )];
                  if (!rows.length) {
                    const w = document.querySelector('#eventListWrap');
                    return w ? w.outerHTML : '';
                  }
                  return '<div id="eventListWrap"><table id="eventContent"><tbody>'
                    + rows.map(r => r.outerHTML).join('')
                    + '</tbody></table></div>';
                }"""
            )
            or ""
        )
    except Exception:
        return ""


def refresh_event_list_in_page(page: Page) -> str:
    """Fetch AJAX in-page, inject eventbox, return rows HTML."""
    try:
        return (
            page.evaluate(
                """async () => {
                  const base = location.href.split('?')[0];
                  const url = base + '?page=componentOnly&component=eventList&ajax=1';
                  let html = '';
                  try {
                    const r = await fetch(url, {
                      headers: {'X-Requested-With': 'XMLHttpRequest'},
                      credentials: 'same-origin',
                    });
                    html = await r.text();
                    const box = document.querySelector('#eventboxContent');
                    if (box && html) box.innerHTML = html;
                  } catch (e) {}
                  try {
                    if (typeof refreshFleetEvents === 'function') refreshFleetEvents(true);
                    else if (typeof getAjaxEventbox === 'function') getAjaxEventbox();
                  } catch (e) {}
                  await new Promise(r => setTimeout(r, 900));
                  const rows = [...document.querySelectorAll(
                    'tr.eventFleet, tr.allianceAttack'
                  )];
                  if (rows.length) {
                    return '<div id="eventListWrap"><table id="eventContent"><tbody>'
                      + rows.map(r => r.outerHTML).join('')
                      + '</tbody></table></div>';
                  }
                  if (html && (html.includes('eventListWrap') || html.includes('eventFleet')))
                    return html;
                  const w = document.querySelector('#eventListWrap');
                  return w ? w.outerHTML : (html || '');
                }"""
            )
            or ""
        )
    except Exception:
        return ""


def event_list_sources(page: Page) -> list[str]:
    """AJAX → DOM → refresh → overview SSR (same order as hostile poll)."""
    out: list[str] = []
    ajax = fetch_event_list_html(page)
    if ajax:
        out.append(ajax)
    dom = dom_event_rows_html(page)
    if dom and dom not in out:
        out.append(dom)
    refreshed = refresh_event_list_in_page(page)
    if refreshed and refreshed not in out:
        out.append(refreshed)
    try:
        base = page.url.split("?")[0]
        ov = page.request.get(f"{base}?page=ingame&component=overview").text() or ""
        if ov and ov not in out:
            out.append(ov)
    except Exception:
        pass
    if not out:
        try:
            out.append(page.content() or "")
        except Exception:
            pass
    return out


def first_event_list_html(page: Page) -> str:
    """AJAX then DOM only (no refresh/overview — those are slow; use event_list_sources)."""
    ajax = fetch_event_list_html(page)
    if ajax and "eventFleet" in ajax:
        return ajax
    dom = dom_event_rows_html(page)
    if dom and ("eventFleet" in dom or "allianceAttack" in dom):
        return dom
    return ajax or dom or ""


def iter_event_fleet_rows(html: str):
    for m in _EVENT_FLEET_ROW_RE.finditer(html or ""):
        yield m.group(0)


def row_attrs(row: str) -> dict[str, str]:
    open_tag = row[: row.find(">") + 1] if ">" in row else row
    return {k.lower(): v for k, v in _ATTR_RE.findall(open_tag)}


def row_arrival_eta(row: str, now: float | None = None) -> float | None:
    now = time.time() if now is None else now
    attrs = row_attrs(row)
    raw = attrs.get("data-arrival-time") or ""
    if not raw.isdigit():
        return None
    eta = int(raw) - now
    return eta if eta >= 0 else None


def row_mission(row: str) -> int | None:
    raw = row_attrs(row).get("data-mission-type") or ""
    try:
        return int(raw)
    except ValueError:
        return None


def row_is_return(row: str) -> bool:
    return (row_attrs(row).get("data-return-flight") or "") in ("true", "1")


def row_dest_coords(row: str) -> tuple[int, int, int] | None:
    coords = _COORDS_RE.findall(row)
    if not coords:
        return None
    g, s, p = coords[-1]
    return int(g), int(s), int(p)


def expo_back_in_html(
    html: str, *, latest: bool = False, now: float | None = None
) -> float | None:
    """Seconds until earliest (or latest) expedition return from HTML."""
    now = time.time() if now is None else now
    best: float | None = None
    for row in iter_event_fleet_rows(html):
        if row_mission(row) != MISSION_EXPEDITION:
            continue
        eta = row_arrival_eta(row, now)
        if eta is None:
            continue
        weight = eta if row_is_return(row) else eta + 3600
        if best is None or (weight > best if latest else weight < best):
            best = weight
    return best


def fleets_max_eta_html(
    html: str, *, now: float | None = None, skip_discovery: bool = True
) -> float:
    now = time.time() if now is None else now
    delay = 0.0
    for row in iter_event_fleet_rows(html):
        mid = row_mission(row)
        if skip_discovery and mid == MISSION_DISCOVERY:
            continue
        eta = row_arrival_eta(row, now)
        if eta is not None and eta > 0:
            delay = max(delay, eta)
    return delay


def fleets_delay_until_sleep_html(
    html: str, sleep_secs: float, *, now: float | None = None
) -> float:
    if sleep_secs <= 0:
        return 0.0
    now = time.time() if now is None else now
    delay = 0.0
    for row in iter_event_fleet_rows(html):
        if row_mission(row) == MISSION_DISCOVERY:
            continue
        eta = row_arrival_eta(row, now)
        if eta is not None and 0 <= eta <= sleep_secs:
            delay = max(delay, eta)
    return delay


if __name__ == "__main__":
    sample = """
    <tr class="eventFleet" id="eventRow-1" data-mission-type="15"
        data-return-flight="true" data-arrival-time="2000"></tr>
    <tr class="eventFleet" id="eventRow-2" data-mission-type="15"
        data-return-flight="false" data-arrival-time="1500"></tr>
    <tr class="eventFleet" id="eventRow-3" data-mission-type="18"
        data-return-flight="false" data-arrival-time="9000"></tr>
    <tr class="eventFleet" id="eventRow-4" data-mission-type="3"
        data-return-flight="false" data-arrival-time="3000"></tr>
    """
    now = 1000.0
    # return weight=1000; outbound weight=500+3600=4100
    assert expo_back_in_html(sample, now=now) == 1000.0
    assert expo_back_in_html(sample, latest=True, now=now) == 4100.0
    assert fleets_max_eta_html(sample, now=now) == 2000.0  # skip discovery
    assert fleets_delay_until_sleep_html(sample, 1500, now=now) == 1000.0
    assert fleets_delay_until_sleep_html(sample, 500, now=now) == 500.0
    assert fleets_delay_until_sleep_html(sample, 400, now=now) == 0.0
    print("event_list ok")
