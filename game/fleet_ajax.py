"""Shared fleetdispatch AJAX post + debug dump (ogamed-style)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

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
        on = [k for k, v in orders.items() if v]
        flags.append("orders=" + (",".join(on) if on else "none"))
    return "; ".join(parts) + (f" [{', '.join(flags)}]" if flags else "")
