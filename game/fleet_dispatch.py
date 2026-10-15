"""Fleet AJAX dispatch: checkTarget + sendFleet (jQuery/fetch in-page)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from .tech import open_component

MISSION_ATTACK = 1
MISSION_TRANSPORT = 3
MISSION_DEPLOY = 4
MISSION_SPY = 6
MISSION_COLONIZE = 7
MISSION_HARVEST = 8
MISSION_EXPEDITION = 15
MISSION_DISCOVERY = 18
DEST_PLANET, DEST_DEBRIS, DEST_MOON = 1, 2, 3

_DEBUG_PATH = Path(__file__).resolve().parent.parent / "logs" / "fleet_debug.jsonl"


def _token(html: str) -> str | None:
    m = re.search(r'var token = "([^"]+)"', html) or re.search(
        r'var fleetSendingToken = "([^"]+)"', html
    )
    return m.group(1) if m else None


def _debug_dump(event: str, payload: dict[str, Any]) -> None:
    """Append one JSON line for offline root-cause (logs/fleet_debug.jsonl)."""
    try:
        _DEBUG_PATH.parent.mkdir(exist_ok=True)
        row = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **payload}
        with _DEBUG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _probe_dispatcher(page: Page) -> dict[str, Any]:
    try:
        return page.evaluate(
            """() => {
              const fd = window.fleetDispatcher;
              if (!fd) return {has: false};
              const cur = fd.currentPlanet || {};
              const tgt = fd.targetPlanet || {};
              return {
                has: true,
                methods: {
                  updateTarget: typeof fd.updateTarget === 'function',
                  refreshTarget: typeof fd.refreshTarget === 'function',
                  checkTarget: typeof fd.checkTarget === 'function',
                  selectShip: typeof fd.selectShip === 'function',
                  submitFleet3: typeof fd.submitFleet3 === 'function',
                  trySubmitFleet: typeof fd.trySubmitFleet === 'function',
                },
                exp: {
                  count: fd.expeditionCount ?? null,
                  max: fd.maxExpeditionCount ?? null,
                },
                current: {
                  g: cur.galaxy ?? null, s: cur.system ?? null,
                  p: cur.position ?? null, id: cur.id ?? null,
                },
                target: {
                  g: tgt.galaxy ?? null, s: tgt.system ?? null,
                  p: tgt.position ?? null, type: tgt.type ?? null,
                },
                mission: fd.mission ?? null,
                expeditionTime: fd.expeditionTime ?? null,
                token: (fd.token || window.token || window.fleetSendingToken || '').toString().slice(0, 12),
                hasJquery: typeof window.jQuery === 'function' || typeof window.$ === 'function',
                checkTargetUrl: typeof checkTargetUrl !== 'undefined' ? String(checkTargetUrl).slice(-80) : null,
              };
            }"""
        ) or {"has": False}
    except Exception as e:
        return {"has": False, "err": str(e)[:120]}


def _is_inquiry_100(resp: dict[str, Any]) -> bool:
    for e in resp.get("errors") or []:
        if isinstance(e, dict) and e.get("error") == 100:
            return True
    err = resp.get("error")
    return isinstance(err, dict) and err.get("error") == 100


def _fleet_post(page: Page, action: str, form: dict[str, str]) -> dict[str, Any]:
    """POST via jQuery.ajax (URL própria ajax=1&asJson=1&cp=, paridade ogamed)."""
    cp_m = re.search(r"[?&]cp=(\d+)", page.url)
    try:
        data = page.evaluate(
            """async ({ action, form }) => {
              // não usar checkTargetUrl do jogo: V13 omite ajax=1 e às vezes cp
              const u = new URL(location.href);
              const cp = u.searchParams.get('cp');
              let url = '?page=ingame&component=fleetdispatch&action='
                + encodeURIComponent(action) + '&ajax=1&asJson=1';
              if (cp) url += '&cp=' + encodeURIComponent(cp);
              const $ = window.jQuery || window.$;
              if (typeof $ === 'function' && $.ajax) {
                const j = await new Promise((resolve) => {
                  $.ajax({
                    url,
                    type: 'POST',
                    dataType: 'json',
                    data: form,
                    success: (resp, _t, xhr) => {
                      const out = (resp && typeof resp === 'object') ? resp : {success:false, message:String(resp)};
                      out._http = xhr ? xhr.status : 200;
                      out._via = 'jquery';
                      out._cp = cp || '';
                      out._action = action;
                      out._url = url;
                      resolve(out);
                    },
                    error: (xhr, _s, err) => {
                      let body = (xhr && xhr.responseText) ? xhr.responseText.slice(0, 200) : String(err);
                      let parsed = null;
                      try { parsed = JSON.parse(xhr.responseText); } catch (e) {}
                      if (parsed && typeof parsed === 'object') {
                        parsed._http = xhr ? xhr.status : 0;
                        parsed._via = 'jquery-error';
                        parsed._cp = cp || '';
                        parsed._action = action;
                        parsed._url = url;
                        resolve(parsed);
                      } else {
                        resolve({
                          success: false,
                          errors: [{ message: 'jquery ' + body }],
                          _http: xhr ? xhr.status : 0,
                          _via: 'jquery-error',
                          _cp: cp || '',
                          _action: action,
                          _url: url,
                        });
                      }
                    },
                  });
                });
                return j;
              }
              const body = new URLSearchParams();
              for (const [k, v] of Object.entries(form || {})) body.set(k, String(v));
              const r = await fetch(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                  'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                  'X-Requested-With': 'XMLHttpRequest',
                },
                body,
              });
              const text = await r.text();
              let j;
              try { j = JSON.parse(text); }
              catch {
                return {
                  success: false,
                  errors: [{ message: 'non-json http' + r.status + ':' + text.slice(0, 100) }],
                  _http: r.status, _via: 'fetch', _cp: cp || '', _action: action, _url: url,
                };
              }
              if (!j || typeof j !== 'object') {
                return {
                  success: false,
                  errors: [{ message: 'resp type=' + typeof j }],
                  _http: r.status, _via: 'fetch', _cp: cp || '', _action: action, _url: url,
                };
              }
              j._http = r.status; j._via = 'fetch'; j._cp = cp || ''; j._action = action; j._url = url;
              return j;
            }""",
            {"action": action, "form": form},
        )
    except Exception as e:
        return {
            "success": False,
            "errors": [{"message": f"post evaluate: {str(e).split(chr(10), 1)[0][:100]}"}],
            "_http": 0,
            "_via": "evaluate-fail",
            "_cp": cp_m.group(1) if cp_m else "",
            "_action": action,
        }
    if not isinstance(data, dict):
        return {
            "success": False,
            "errors": [{"message": f"resp type={type(data).__name__}"}],
            "_http": 0,
            "_via": "bad-type",
            "_cp": cp_m.group(1) if cp_m else "",
            "_action": action,
        }
    return data


def _err_bits(resp: dict[str, Any]) -> str:
    parts: list[str] = []
    for e in (resp.get("errors") or [])[:3]:
        if isinstance(e, dict):
            m = str(e.get("message") or "?")
            c = e.get("error")
            parts.append(f"{m}#{c}" if c is not None else m)
        else:
            parts.append(str(e)[:80])
    if not parts:
        top = resp.get("message")
        parts.append(str(top)[:100] if top else "sem errors[]")
    flags: list[str] = []
    for k in ("success", "targetOk", "ok", "status", "error"):
        if k in resp and resp[k] is not None and resp[k] != "":
            flags.append(f"{k}={resp[k]!r}" if k in ("status", "error") else f"{k}={resp[k]}")
    for k in ("_http", "_via", "_cp"):
        if resp.get(k) not in (None, ""):
            flags.append(f"{k[1:]}={resp[k]}")
    extra = [k for k in ("fleetSendingToken", "newAjaxToken", "redirectUrl") if resp.get(k)]
    if extra:
        flags.append("has:" + "+".join(extra))
    tp = resp.get("targetPlanet")
    if isinstance(tp, dict) and tp:
        flags.append(
            f"tgt=[{tp.get('galaxy')}:{tp.get('system')}:{tp.get('position')}]"
            f"/{tp.get('type')}"
        )
    orders = resp.get("orders")
    if isinstance(orders, dict):
        # quais missões o servidor liberou
        on = [k for k, v in orders.items() if v]
        flags.append("orders=" + (",".join(on) if on else "none"))
    return "; ".join(parts) + (f" [{', '.join(flags)}]" if flags else "")


def _form_snip(form: dict[str, str]) -> str:
    ships = ",".join(
        f"{k[2:]}×{v}"
        for k, v in sorted(form.items())
        if k.startswith("am") and int(v or 0) > 0
    )
    keys = ",".join(sorted(k for k in form if not k.startswith("am") and k != "token"))
    return (
        f"[{form.get('galaxy')}:{form.get('system')}:{form.get('position')}]"
        f" type={form.get('type')} mission={form.get('mission', '?')}"
        f" speed={form.get('speed', '-')} hold={form.get('holdingtime', '-')}"
        f" ships={ships or '—'} formKeys={keys}"
    )


def _planet_deut_snip(page: Page) -> str:
    try:
        from .resources import current_resources, parse_ogame_int

        r = current_resources(page)
        return (
            f"planet M{parse_ogame_int(r.get('metal', '0'))}"
            f" C{parse_ogame_int(r.get('crystal', '0'))}"
            f" D{parse_ogame_int(r.get('deut', '0'))}"
        )
    except Exception:
        return "planet res=?"


def _fail_check(
    page: Page, form: dict[str, str], check: dict[str, Any], token: str
) -> str:
    probe = _probe_dispatcher(page)
    # resposta completa (sem tokens longos) p/ fleet_debug.jsonl
    safe_resp = {
        k: v
        for k, v in check.items()
        if k
        not in (
            "fleetSendingToken",
            "newAjaxToken",
            "components",
        )
    }
    if check.get("newAjaxToken"):
        safe_resp["newAjaxToken"] = str(check["newAjaxToken"])[:12] + "…"
    _debug_dump(
        "checkTarget_fail",
        {
            "form": {k: v for k, v in form.items() if k != "token"},
            "token_prefix": token[:12],
            "response": safe_resp,
            "dispatcher": probe,
            "url": page.url[-120:],
        },
    )
    return (
        f"fail checkTarget: {_err_bits(check)} | {_form_snip(form)} | "
        f"tok={token[:8]}… | {_planet_deut_snip(page)} | "
        f"fd={probe.get('has')} jq={probe.get('hasJquery')} "
        f"exp={probe.get('exp')} via={check.get('_via')}"
    )


def send_fleet(
    page: Page,
    ships: dict[int, int],
    galaxy: int,
    system: int,
    position: int,
    *,
    mission: int,
    speed: int = 10,
    dest_type: int = DEST_PLANET,
    holding: int = 0,
    metal: int = 0,
    crystal: int = 0,
    deut: int = 0,
) -> str:
    """AJAX fleetdispatch. speed 1..10 (=10%..100%). Returns ok / fail:…"""
    open_component(page, "fleetdispatch")
    html = page.content()
    token = _token(html)
    if not token:
        _debug_dump("no_token", {"url": page.url[-120:], "dispatcher": _probe_dispatcher(page)})
        return "fail: sem token (fleetdispatch)"
    # payload mínimo (ogamed + userscripts) — sem hidden extras da UI
    form: dict[str, str] = {
        "token": token,
        "galaxy": str(galaxy),
        "system": str(system),
        "position": str(position),
        "type": str(dest_type),
        "union": "0",
    }
    for sid, n in ships.items():
        if n > 0:
            form[f"am{sid}"] = str(int(n))
    check = _fleet_post(page, "checkTarget", form)
    if not (check.get("targetOk") or check.get("success") or check.get("ok")):
        # V13: checkTarget AJAX #100 — fallback UI (fleetDispatcher), como Quick Expe
        if _is_inquiry_100(check):
            from .fleet_ui import send_fleet_ui

            _debug_dump(
                "checkTarget_100_ui_fallback",
                {
                    "form": {k: v for k, v in form.items() if k != "token"},
                    "url": check.get("_url"),
                    "via": check.get("_via"),
                },
            )
            ui = send_fleet_ui(
                page,
                ships,
                galaxy,
                system,
                position,
                mission=mission,
                speed=speed,
                dest_type=dest_type,
                holding=holding,
                metal=metal,
                crystal=crystal,
                deut=deut,
            )
            if ui == "ok":
                return "ok"
            return f"{_fail_check(page, form, check, token)} | ui={ui}"
        return _fail_check(page, form, check, token)
    if check.get("newAjaxToken"):
        form["token"] = check["newAjaxToken"]
    form.update(
        {
            "speed": str(max(1, min(10, int(speed)))),
            "metal": str(max(0, int(metal))),
            "crystal": str(max(0, int(crystal))),
            "deuterium": str(max(0, int(deut))),
            "prioMetal": "1",
            "prioCrystal": "2",
            "prioDeuterium": "3",
            "mission": str(int(mission)),
            "retreatAfterDefenderRetreat": "0",
            "holdingtime": str(max(0, min(18, int(holding)))),
        }
    )
    res = _fleet_post(page, "sendFleet", form)
    if res.get("success"):
        return "ok"
    _debug_dump(
        "sendFleet_fail",
        {
            "form": {k: v for k, v in form.items() if k != "token"},
            "response": {
                k: v
                for k, v in res.items()
                if k not in ("fleetSendingToken", "newAjaxToken", "components")
            },
            "dispatcher": _probe_dispatcher(page),
        },
    )
    tok2 = str(form.get("token") or "")[:8]
    return (
        f"fail sendFleet: {_err_bits(res)} | {_form_snip(form)} | "
        f"tok={tok2}… | {_planet_deut_snip(page)} | via={res.get('_via')}"
    )


def send_discovery(page: Page, galaxy: int, system: int, position: int) -> str:
    """POST sendDiscoveryFleet (sem naves). Custo ~5k/1k/500. Returns ok / fail:…"""
    open_component(page, "fleetdispatch")
    html = page.content()
    token = _token(html)
    if not token:
        _debug_dump("discovery_no_token", {"url": page.url[-120:]})
        return "fail: sem token (fleetdispatch)"
    form = {
        "token": token,
        "galaxy": str(int(galaxy)),
        "system": str(int(system)),
        "position": str(int(position)),
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


def send_expedition(
    page: Page,
    ships: dict[int, int],
    galaxy: int,
    system: int,
    *,
    holding: int = 1,
    deut: int = 0,
) -> str:
    """Send expo to [g:s:16]. V13: UI fleetDispatcher (AJAX checkTarget quebra com #100)."""
    from .fleet_ui import send_fleet_ui

    return send_fleet_ui(
        page,
        ships,
        galaxy,
        system,
        16,
        mission=MISSION_EXPEDITION,
        speed=10,
        dest_type=DEST_PLANET,
        holding=holding,
        deut=deut,
    )


if __name__ == "__main__":
    sample = {
        "success": False,
        "targetOk": False,
        "errors": [{"message": "LOCA_ERROR_INQUIRY_NOT_WORKED_TRYAGAIN", "error": 100}],
        "_http": 200,
        "_via": "jquery",
        "status": "failure",
        "error": 100,
    }
    bits = _err_bits(sample)
    assert "LOCA_ERROR_INQUIRY_NOT_WORKED_TRYAGAIN#100" in bits
    assert "via=jquery" in bits
    print("fleet_dispatch ok")
