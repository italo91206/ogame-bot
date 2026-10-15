"""Debug helpers for fleet_ui (snap / ajax hook / jsonl dump)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

_DEBUG_PATH = Path(__file__).resolve().parent.parent / "logs" / "fleet_debug.jsonl"

_SNAP_JS = """() => {
  const btn = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return { exists: false };
    const st = getComputedStyle(el);
    return {
      exists: true,
      id: el.id || null,
      tag: el.tagName,
      cls: (el.className || '').toString().slice(0, 80),
      off: el.classList.contains('off'),
      disabled: el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true',
      display: st.display,
      visibility: st.visibility,
      text: (el.textContent || '').trim().slice(0, 40),
    };
  };
  const panel = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return { exists: false };
    const st = getComputedStyle(el);
    return {
      exists: true,
      display: st.display,
      visibility: st.visibility,
      cls: (el.className || '').toString().slice(0, 60),
    };
  };
  const fd = window.fleetDispatcher;
  const ships = [];
  if (fd && Array.isArray(fd.shipsToSend)) {
    for (const s of fd.shipsToSend) {
      if (s && s.number > 0) ships.push({ id: s.id, n: s.number });
    }
  }
  // selected ship inputs
  const am = {};
  document.querySelectorAll('input[name^="am"]').forEach((el) => {
    const v = parseInt(el.value || '0', 10);
    if (v > 0) am[el.name] = v;
  });
  const errs = [];
  document.querySelectorAll('.error, .fleetStatus, #errorBox, .msg_error, .warning')
    .forEach((el) => {
      const t = (el.textContent || '').trim();
      if (t) errs.push(t.slice(0, 120));
    });
  const tgt = fd && fd.targetPlanet ? fd.targetPlanet : {};
  const cur = fd && fd.currentPlanet ? fd.currentPlanet : {};
  return {
    url: location.href.slice(-120),
    fleet1: panel('#fleet1'),
    fleet2: panel('#fleet2'),
    fleet3: panel('#fleet3'),
    buttons: {
      c2: btn('#continueToFleet2'),
      c3: btn('#continueToFleet3'),
      send: btn('#sendFleet'),
      m15: btn('#missionButton15'),
    },
    inputs: {
      galaxy: (document.querySelector('#galaxy') || {}).value ?? null,
      system: (document.querySelector('#system') || {}).value ?? null,
      position: (document.querySelector('#position') || {}).value ?? null,
    },
    am,
    fd: fd ? {
      mission: fd.mission ?? null,
      speed: fd.speed ?? null,
      expeditionTime: fd.expeditionTime ?? null,
      targetOk: fd.targetOk ?? null,
      targetIsOwn: fd.targetIsOwn ?? null,
      targetInhabited: fd.targetInhabited ?? null,
      targetPlanet: { g: tgt.galaxy, s: tgt.system, p: tgt.position, type: tgt.type },
      currentPlanet: { g: cur.galaxy, s: cur.system, p: cur.position },
      shipsToSend: ships,
      fleetCount: fd.fleetCount ?? null,
      expeditionCount: fd.expeditionCount ?? null,
      maxExpeditionCount: fd.maxExpeditionCount ?? null,
      token: (fd.token || window.token || '').toString().slice(0, 12),
    } : null,
    errorsVisible: errs.slice(0, 5),
    ajaxLog: (window.__fleetAjaxLog || []).slice(-8),
  };
}"""


def debug_dump(event: str, payload: dict[str, Any]) -> None:
    try:
        _DEBUG_PATH.parent.mkdir(exist_ok=True)
        row = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **payload}
        with _DEBUG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def install_ajax_hook(page: Page) -> None:
    page.evaluate(
        """() => {
          if (window.__fleetAjaxHooked) return;
          window.__fleetAjaxHooked = true;
          window.__fleetAjaxLog = [];
          const push = (row) => {
            try {
              window.__fleetAjaxLog.push(row);
              if (window.__fleetAjaxLog.length > 30) window.__fleetAjaxLog.shift();
            } catch (e) {}
          };
          const $ = window.jQuery || window.$;
          if (typeof $ === 'function' && $.ajax) {
            const orig = $.ajax;
            $.ajax = function(url, opts) {
              let o = opts;
              if (typeof url === 'object') { o = url; url = o.url; }
              o = o || {};
              const u = String(o.url || url || '');
              const interesting = /checkTarget|sendFleet|fleetdispatch/i.test(u);
              if (!interesting) return orig.apply(this, arguments);
              const t0 = Date.now();
              const prevSucc = o.success;
              const prevErr = o.error;
              o.success = function(data, textStatus, xhr) {
                push({
                  url: u.slice(-100),
                  ms: Date.now() - t0,
                  ok: true,
                  status: xhr ? xhr.status : null,
                  body: (typeof data === 'object')
                    ? {
                        success: data.success,
                        targetOk: data.targetOk,
                        status: data.status,
                        errors: data.errors,
                        error: data.error,
                      }
                    : String(data).slice(0, 120),
                });
                if (prevSucc) return prevSucc.apply(this, arguments);
              };
              o.error = function(xhr, textStatus, err) {
                push({
                  url: u.slice(-100),
                  ms: Date.now() - t0,
                  ok: false,
                  status: xhr ? xhr.status : null,
                  body: xhr && xhr.responseText ? xhr.responseText.slice(0, 160) : String(err),
                });
                if (prevErr) return prevErr.apply(this, arguments);
              };
              return orig.call(this, o);
            };
          }
        }"""
    )


def snap(page: Page) -> dict[str, Any]:
    try:
        return page.evaluate(_SNAP_JS) or {}
    except Exception as e:
        return {"snap_err": str(e)[:120]}
