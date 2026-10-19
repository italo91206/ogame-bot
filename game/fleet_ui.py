"""Fleet send via in-page fleetDispatcher (Quick Expe / OG-CoPilot path)."""
from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

from .fleet_ui_debug import debug_dump, install_ajax_hook, snap
from .tech import open_component


def send_fleet_ui(
    page: Page,
    ships: dict[int, int],
    galaxy: int,
    system: int,
    position: int,
    *,
    mission: int,
    speed: int = 10,
    dest_type: int = 1,
    holding: int = 0,
    metal: int = 0,
    crystal: int = 0,
    deut: int = 0,
    force_own_sibling: bool = False,
) -> str:
    """Configure fleetDispatcher + click continue/send. Returns ok / fail:…"""
    open_component(page, "fleetdispatch")
    install_ajax_hook(page)
    samples: list[dict[str, Any]] = [{"t": "boot", **snap(page)}]

    setup = page.evaluate(
        """({ ships, galaxy, system, position, mission, speed, destType, holding, metal, crystal, deut, forceSibling }) => {
          const fd = window.fleetDispatcher;
          if (!fd) return { ok: false, err: 'no fleetDispatcher' };
          const setVal = (sel, v) => {
            const el = document.querySelector(sel);
            if (el) {
              el.value = String(v);
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
            }
          };
          // moon↔planet same coords: click type button before updateTarget
          const typeSel = destType === 3 ? '#moon' : destType === 2 ? '#debris' : '#planet';
          const typeBtn = document.querySelector(typeSel);
          if (typeBtn) typeBtn.click();
          setVal('#galaxy', galaxy);
          setVal('#system', system);
          setVal('#position', position);
          fd.targetPlanet.galaxy = galaxy;
          fd.targetPlanet.system = system;
          fd.targetPlanet.position = position;
          fd.targetPlanet.type = destType;
          fd.mission = mission;
          fd.speed = Math.max(1, Math.min(10, speed));
          if (mission === 15) fd.expeditionTime = Math.max(1, Math.min(18, holding || 1));
          else if (holding) fd.holdingTime = holding;
          fd.cargoMetal = metal;
          fd.cargoCrystal = crystal;
          fd.cargoDeuterium = deut;
          for (const [id, n] of Object.entries(ships || {})) {
            if (+n > 0 && typeof fd.selectShip === 'function') fd.selectShip(+id, +n);
          }
          if (forceSibling) {
            // V13 checkTarget #100 on own sibling — unlock UI without server OK
            fd.targetOk = true;
          } else {
            if (typeof fd.refreshTarget === 'function') fd.refreshTarget();
            if (typeof fd.updateTarget === 'function') fd.updateTarget();
            if (typeof fd.refresh === 'function') fd.refresh();
          }
          const proto = Object.getPrototypeOf(fd) || {};
          const methods = Object.getOwnPropertyNames(proto)
            .filter((k) => typeof fd[k] === 'function')
            .slice(0, 40);
          let updateSrc = '';
          try { updateSrc = Function.prototype.toString.call(fd.updateTarget).slice(0, 240); }
          catch (e) {}
          return {
            ok: true,
            mission: fd.mission,
            forceSibling: !!forceSibling,
            tgt: {
              g: fd.targetPlanet.galaxy,
              s: fd.targetPlanet.system,
              p: fd.targetPlanet.position,
              type: fd.targetPlanet.type,
            },
            expTime: fd.expeditionTime ?? null,
            methods,
            updateSrc,
          };
        }""",
        {
            "ships": {str(k): int(v) for k, v in ships.items() if v > 0},
            "galaxy": int(galaxy),
            "system": int(system),
            "position": int(position),
            "mission": int(mission),
            "speed": int(speed),
            "destType": int(dest_type),
            "holding": int(holding),
            "metal": int(metal),
            "crystal": int(crystal),
            "deut": int(deut),
            "forceSibling": bool(force_own_sibling),
        },
    )
    samples.append({"t": "after_setup", **snap(page)})
    if not isinstance(setup, dict) or not setup.get("ok"):
        debug_dump("ui_setup_fail", {"setup": setup, "samples": samples})
        return f"fail ui-setup: {(setup or {}).get('err', setup)!r}"

    samples.append({"t": "pre_c2", **snap(page)})

    # ponytail: sendFleet redirect destrói o context do evaluate se esperarmos ajax;
    # return logo após click; navigation destroyed → ok.
    try:
        click = page.evaluate(
            """async ({ mission, metal, crystal, deut, forceSibling }) => {
              const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
              const snapMini = () => {
                const b = (sel) => {
                  const el = document.querySelector(sel);
                  if (!el) return null;
                  return {
                    off: el.classList.contains('off'),
                    dis: el.hasAttribute('disabled'),
                    cls: (el.className || '').toString().slice(0, 40),
                  };
                };
                const fd = window.fleetDispatcher;
                let shipsN = 0;
                if (fd && Array.isArray(fd.shipsToSend)) {
                  for (const s of fd.shipsToSend) if (s && s.number > 0) shipsN += s.number;
                }
                const cargoIn = (sel) => {
                  const el = document.querySelector(sel);
                  return el ? String(el.value || '') : null;
                };
                return {
                  c2: b('#continueToFleet2'),
                  c3: b('#continueToFleet3'),
                  send: b('#sendFleet'),
                  mission: fd ? fd.mission : null,
                  targetOk: fd ? fd.targetOk : null,
                  shipsN,
                  cargo: fd ? {
                    m: fd.cargoMetal ?? null,
                    c: fd.cargoCrystal ?? null,
                    d: fd.cargoDeuterium ?? null,
                  } : null,
                  cargoInputs: {
                    m: cargoIn('#metal'),
                    c: cargoIn('#crystal'),
                    d: cargoIn('#deuterium'),
                  },
                  ajax: (window.__fleetAjaxLog || []).slice(-3),
                };
              };
              // V13: refresh/c2 zera cargo do setup — reaplicar na tela de missão antes do send
              const applyCargo = () => {
                const fd = window.fleetDispatcher;
                const m = Math.max(0, +metal || 0);
                const c = Math.max(0, +crystal || 0);
                const d = Math.max(0, +deut || 0);
                if (fd) {
                  fd.cargoMetal = m;
                  fd.cargoCrystal = c;
                  fd.cargoDeuterium = d;
                }
                const setVal = (sel, v) => {
                  const el = document.querySelector(sel);
                  if (!el) return null;
                  el.value = String(v);
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  return String(el.value || '');
                };
                return {
                  want: { m, c, d },
                  inputs: {
                    m: setVal('#metal', m) ?? setVal('input[name=\"metal\"]', m),
                    c: setVal('#crystal', c) ?? setVal('input[name=\"crystal\"]', c),
                    d: setVal('#deuterium', d) ?? setVal('input[name=\"deuterium\"]', d),
                  },
                  fd: fd ? { m: fd.cargoMetal, c: fd.cargoCrystal, d: fd.cargoDeuterium } : null,
                };
              };
              const cargoSum = (row) => {
                const n = (v) => parseInt(String(v ?? '0').replace(/\\D/g, '') || '0', 10) || 0;
                if (!row) return 0;
                return n(row.m) + n(row.c) + n(row.d);
              };
              const timeline = [];
              const btnUsable = (sel) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                if (el.classList.contains('off')) return false;
                if (el.hasAttribute('disabled')) return false;
                if (el.getAttribute('aria-disabled') === 'true') return false;
                return true;
              };
              const checkTargetOk = () => {
                const fd = window.fleetDispatcher;
                if (fd && fd.targetOk === true) return true;
                for (const row of (window.__fleetAjaxLog || [])) {
                  const u = String(row.url || '');
                  if (!/checkTarget/i.test(u)) continue;
                  const b = row.body || {};
                  if (b.targetOk === true || b.success === true) return true;
                }
                return false;
              };
              const shipsSelected = () => {
                const fd = window.fleetDispatcher;
                if (!fd || !Array.isArray(fd.shipsToSend)) return false;
                return fd.shipsToSend.some((s) => s && s.number > 0);
              };
              const waitGate = async (ms, label, pred) => {
                const t0 = Date.now();
                let last = 0;
                while (Date.now() - t0 < ms) {
                  if (Date.now() - last > 2000) {
                    timeline.push({ t: Date.now() - t0, wait: label, ...snapMini() });
                    last = Date.now();
                  }
                  if (pred()) {
                    timeline.push({ t: Date.now() - t0, gate: label, ...snapMini() });
                    return true;
                  }
                  await sleep(200);
                }
                timeline.push({ t: Date.now() - t0, timeout: label, ...snapMini() });
                return false;
              };
              await sleep(800);
              if (forceSibling) {
                const fd0 = window.fleetDispatcher;
                if (fd0) fd0.targetOk = true;
                // unlock continue buttons when server checkTarget stays broken
                for (const sel of ['#continueToFleet2', '#continueToFleet3', '#sendFleet']) {
                  const el = document.querySelector(sel);
                  if (!el) continue;
                  el.classList.remove('off');
                  el.removeAttribute('disabled');
                }
              }
              const gate1 = await waitGate(
                forceSibling ? 4000 : 12000,
                'pre_c2_gate',
                () => shipsSelected() && (
                  forceSibling
                  || checkTargetOk()
                  || btnUsable('#continueToFleet2')
                ),
              );
              if (!gate1 && !forceSibling) {
                return { ok: false, err: 'pre_c2 gate timeout (ships/targetOk)', step: 1, timeline };
              }
              if (!forceSibling) {
                const lastCt = [...(window.__fleetAjaxLog || [])].reverse()
                  .find((r) => /checkTarget/i.test(String(r.url || '')));
                if (lastCt && lastCt.body && lastCt.body.errors) {
                  const e100 = (lastCt.body.errors || []).some((e) => e && e.error === 100);
                  if (e100) {
                    return {
                      ok: false,
                      err: 'checkTarget #100 via updateTarget (bloqueia fleet3)',
                      step: 1,
                      timeline,
                      lastCt,
                    };
                  }
                }
              }
              if (!btnUsable('#continueToFleet2') && !forceSibling) {
                const el = document.querySelector('#continueToFleet2');
                if (!el) return { ok: false, err: 'continueToFleet2 missing', step: 2, timeline };
              }
              const fd = window.fleetDispatcher;
              if (fd && typeof fd.trySubmitFleet1 === 'function') {
                try { fd.trySubmitFleet1(); } catch (e) {}
              } else {
                const c2 = document.querySelector('#continueToFleet2');
                if (c2) c2.click();
              }
              timeline.push({ t: 0, clicked: 'c2', ...snapMini() });
              await sleep(1000);
              if (fd && fd.targetPlanet) {
                const tp = fd.targetPlanet;
                for (const [sel, v] of [['#galaxy', tp.galaxy], ['#system', tp.system], ['#position', tp.position]]) {
                  const el = document.querySelector(sel);
                  if (el) {
                    el.value = String(v);
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                  }
                }
                if (typeof fd.updateTarget === 'function') fd.updateTarget();
                if (typeof fd.refresh === 'function') fd.refresh();
              }
              await sleep(1200);
              const c3 = document.querySelector('#continueToFleet3');
              if (c3 && btnUsable('#continueToFleet3')) {
                c3.click();
                timeline.push({ t: 0, clicked: 'c3', ...snapMini() });
                await sleep(500);
              }
              if (fd) {
                fd.mission = mission;
                if (forceSibling) fd.targetOk = true;
              }
              const mb = document.querySelector('#missionButton' + mission);
              if (mb) mb.click();
              await sleep(300);
              const sendReady = () => {
                const el = document.querySelector('#sendFleet');
                if (!el) return false;
                if (forceSibling) {
                  el.classList.remove('off');
                  el.removeAttribute('disabled');
                  return true;
                }
                if (el.classList.contains('off')) return false;
                if (el.classList.contains('on')) return true;
                return btnUsable('#sendFleet');
              };
              const gateS = await waitGate(forceSibling ? 3000 : 12000, 'send_gate', sendReady);
              if (!sendReady()) {
                // last resort sibling: fleetDispatcher submit helpers
                if (forceSibling && fd) {
                  try {
                    if (typeof fd.trySubmitFleet === 'function') fd.trySubmitFleet();
                    else if (typeof fd.submitFleet3 === 'function') fd.submitFleet3();
                    timeline.push({ t: 0, siblingSubmit: true, ...snapMini() });
                    return { ok: true, clicked: true, siblingSubmit: true, timeline };
                  } catch (e) {
                    return {
                      ok: false,
                      err: 'sibling submit: ' + String(e).slice(0, 80),
                      step: 4,
                      timeline,
                    };
                  }
                }
                return {
                  ok: false,
                  err: 'sendFleet timeout (V13: sem #continueToFleet3)',
                  step: 4,
                  timeline,
                  gateS,
                  lastCt: [...(window.__fleetAjaxLog || [])].reverse()
                    .find((r) => /checkTarget/i.test(String(r.url || ''))),
                };
              }
              const cargo = applyCargo();
              timeline.push({ t: 0, cargoApplied: cargo, ...snapMini() });
              const need = cargoSum(cargo.want);
              if (need > 0 && cargoSum(cargo.inputs) <= 0 && cargoSum(cargo.fd) <= 0) {
                return {
                  ok: false,
                  err: 'cargo empty before send',
                  step: 5,
                  cargo,
                  timeline,
                };
              }
              const sendBtn = document.querySelector('#sendFleet');
              if (!sendBtn) {
                return { ok: false, err: 'sendFleet missing', step: 6, timeline };
              }
              sendBtn.click();
              // não await ajax — redirect mata o context
              return { ok: true, clicked: true, cargo, timeline, forceSibling: !!forceSibling };
            }""",
            {
                "mission": int(mission),
                "metal": int(metal),
                "crystal": int(crystal),
                "deut": int(deut),
                "forceSibling": bool(force_own_sibling),
            },
        )
    except Exception as e:
        err = str(e).lower()
        if "execution context" in err or "navigat" in err or "destroyed" in err:
            debug_dump("ui_nav_ok", {"setup": setup.get("tgt"), "err": str(e)[:160]})
            return "ok"
        raise

    try:
        samples.append({"t": "final", **snap(page)})
    except Exception:
        samples.append({"t": "final", "snap": "nav"})

    if not isinstance(click, dict) or not click.get("ok"):
        debug_dump(
            "ui_click_fail",
            {
                "setup": {
                    k: setup.get(k)
                    for k in ("mission", "tgt", "expTime", "methods", "updateSrc")
                },
                "click": click,
                "samples": samples,
            },
        )
        tl = (click or {}).get("timeline") or []
        last_ajax = None
        for s in reversed(samples):
            al = s.get("ajaxLog") or []
            if al:
                last_ajax = al[-1]
                break
        if not last_ajax and tl:
            for row in reversed(tl):
                if row.get("ajax"):
                    last_ajax = row["ajax"][-1]
                    break
        return (
            f"fail ui-click: {(click or {}).get('err', click)!r} "
            f"setup={setup.get('tgt')} mission={setup.get('mission')} "
            f"ajax={last_ajax!r} samples={len(samples)}"
        )
    debug_dump("ui_ok", {"setup": setup.get("tgt"), "click": click})
    return "ok"


if __name__ == "__main__":
    assert callable(send_fleet_ui)
    print("fleet_ui ok")
