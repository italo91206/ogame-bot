"""Login, resume, revive."""
from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page, Playwright

from .browser import launch_browser, new_context, wait_captcha
from .lobby import (
    _accept_cookies,
    _enter_universe,
    _game_host,
    _lobby_token,
    _resolve_server,
    _server_host,
)
from .models import LogFn, _noop

def resume_session(page: Page, cred: dict, log: LogFn = _noop) -> Page | None:
    """Reusa cookies do storage_state; None se expirados."""
    lobby = cred.get("Lobby") or "lobby"
    uni = cred["Universe"]
    lang = cred.get("Language") or "br"
    host = _game_host(page.context)

    # cookie de outro uni (ex. Kalyke) não serve p/ target
    token = _lobby_token(page.context)
    if host and token:
        try:
            req = page.context.request
            hdr = {"Authorization": f"Bearer {token}"}
            servers = req.get(
                f"https://{lobby}.ogame.gameforge.com/api/servers", headers=hdr
            ).json()
            server = _resolve_server(servers, uni, lang) if isinstance(servers, list) else None
            if server and host != _server_host(server):
                log(f"cookie {host} ≠ {uni} — lobby", "warn")
                host = None
        except Exception:
            pass

    if host:
        try:
            page.goto(
                f"https://{host}/game/index.php?page=ingame&component=overview",
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            page.wait_for_selector("#resources_metal", timeout=20_000)
            log("sessão reaproveitada", "ok")
            return page
        except Exception as e:
            # ponytail: goto timeout = cookie/rede morta → lobby, não crash
            log(f"cookie jogo falhou ({type(e).__name__}) — lobby", "warn")

    try:
        page.goto(
            f"https://{lobby}.ogame.gameforge.com/",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
    except Exception as e:
        log(f"lobby goto falhou ({type(e).__name__})", "warn")
        return None
    _accept_cookies(page)
    try:
        if page.get_by_text("Log in", exact=True).is_visible(timeout=2500):
            log("sessão expirada — login completo", "warn")
            return None
    except Exception:
        pass
    try:
        page.wait_for_url(re.compile(r".*/(accounts|hub)"), timeout=15_000)
    except Exception:
        log("sessão inválida — login completo", "warn")
        return None
    log("sessão lobby ok", "ok")
    try:
        return _enter_universe(page, cred, log)
    except Exception as e:
        log(f"resume falhou ({e}) — login completo", "warn")
        return None


def login(page: Page, cred: dict, log: LogFn = _noop) -> Page:
    """Gameforge login → universe → returns game page."""
    lobby = cred.get("Lobby") or "lobby"
    page.goto(f"https://{lobby}.ogame.gameforge.com/", wait_until="domcontentloaded")
    _accept_cookies(page)

    page.get_by_text("Log in", exact=True).click()
    page.fill('input[type="email"]', cred["Email"])
    page.fill('input[type="password"]', cred["Password"])
    page.get_by_role("button", name=re.compile(r"^(Log in|Login|Entrar)$", re.I)).click()

    log("aguardando login (resolva captcha se aparecer)", "warn")
    wait_captcha(page, log)
    page.wait_for_url(re.compile(r".*/(accounts|hub)"), timeout=180_000)
    log("login Gameforge ok", "ok")
    return _enter_universe(page, cred, log)


def revive_headless(
    p: Playwright,
    conf: dict,
    storage: Path,
    cred: dict,
    log: LogFn = _noop,
) -> Page:
    """Janela fechada pelo user → headless novo a partir do session file."""
    browser = launch_browser(p, headless=True)
    ctx = new_context(browser, conf, storage_state=storage)
    page = ctx.new_page()
    game = resume_session(page, cred, log=log)
    if game is None:
        raise RuntimeError("sessão inválida após fechar o browser")
    log("headless on (após fechar janela)", "ok")
    return game
