"""Fleet AJAX dispatch: checkTarget + sendFleet (jQuery/fetch in-page)."""
from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

from .fleet_ajax import _debug_dump, _err_bits, _fleet_post, _token
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


def _hidden_fleet_fields(page: Page) -> dict[str, str]:
    """Hidden inputs on fleetdispatch (ogamed ExtractHiddenFields)."""
    try:
        raw = page.evaluate(
            """() => {
              const out = {};
              document.querySelectorAll(
                'form input[type=hidden], #fleetdispatchcomponent input[type=hidden]'
              ).forEach((el) => {
                if (el.name && el.name !== 'token') out[el.name] = String(el.value || '');
              });
              return out;
            }"""
        )
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _current_celestial_type(page: Page) -> int | None:
    """1=planet, 3=moon; None if unknown."""
    try:
        t = page.evaluate(
            """() => {
              const fd = window.fleetDispatcher;
              if (fd && fd.currentPlanet && fd.currentPlanet.type != null)
                return Number(fd.currentPlanet.type);
              if (document.querySelector(
                '#planetList .hightlightMoon, #planetList .smallplanet.hightlightMoon'
              )) return 3;
              const row = document.querySelector(
                '#planetList .smallplanet.active, #planetList .hightlightPlanet'
              );
              if (row && row.querySelector('a.moonlink.active')) return 3;
              return 1;
            }"""
        )
        return int(t) if t in (1, 2, 3) else None
    except Exception:
        return None


def _is_own_sibling_dest(
    page: Page, galaxy: int, system: int, position: int, dest_type: int
) -> bool:
    """True if dest is same G:S:P as current celestial but other type (moon↔planet)."""
    if int(dest_type) not in (DEST_PLANET, DEST_MOON):
        return False
    probe = _probe_dispatcher(page)
    cur = probe.get("current") if isinstance(probe, dict) else None
    if not isinstance(cur, dict):
        return False
    try:
        if (
            int(cur.get("g") or -1) != int(galaxy)
            or int(cur.get("s") or -1) != int(system)
            or int(cur.get("p") or -1) != int(position)
        ):
            return False
    except (TypeError, ValueError):
        return False
    cur_type = _current_celestial_type(page)
    if cur_type is None:
        return False
    return int(cur_type) != int(dest_type)


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
    sibling = _is_own_sibling_dest(page, galaxy, system, position, dest_type)
    # ogamed: hidden fields + coords/ships; V13 moon↔planet same G:S:P often #100
    form: dict[str, str] = dict(_hidden_fleet_fields(page))
    form.update(
        {
            "token": token,
            "galaxy": str(galaxy),
            "system": str(system),
            "position": str(position),
            "type": str(dest_type),
            "union": "0",
        }
    )
    for sid, n in ships.items():
        if n > 0:
            form[f"am{sid}"] = str(int(n))
    # sibling: UI first (force own dest) — AJAX checkTarget breaks on same coords
    if sibling:
        from .fleet_ui import send_fleet_ui

        _debug_dump(
            "sibling_ui_first",
            {
                "form": {k: v for k, v in form.items() if k != "token"},
                "dest_type": dest_type,
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
            force_own_sibling=True,
        )
        if ui == "ok":
            return "ok"
        # fall through to AJAX; keep ui err for final message
        sibling_ui_err = ui
    else:
        sibling_ui_err = None

    check = _fleet_post(page, "checkTarget", form)
    if not (check.get("targetOk") or check.get("success") or check.get("ok")):
        # V13: checkTarget AJAX #100 — retry once (TRYAGAIN) then UI fallback
        if _is_inquiry_100(check):
            page.wait_for_timeout(600)
            tok2 = _token(page.content()) or form.get("token") or token
            form["token"] = tok2
            form.update(_hidden_fleet_fields(page))
            check = _fleet_post(page, "checkTarget", form)
        if not (check.get("targetOk") or check.get("success") or check.get("ok")):
            if _is_inquiry_100(check):
                from .fleet_ui import send_fleet_ui

                _debug_dump(
                    "checkTarget_100_ui_fallback",
                    {
                        "form": {k: v for k, v in form.items() if k != "token"},
                        "url": check.get("_url"),
                        "via": check.get("_via"),
                        "sibling": sibling,
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
                    force_own_sibling=sibling,
                )
                if ui == "ok":
                    return "ok"
                base = _fail_check(page, form, check, token)
                if sibling_ui_err:
                    return f"{base} | ui={ui} | sibling_ui={sibling_ui_err}"
                return f"{base} | ui={ui}"
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
