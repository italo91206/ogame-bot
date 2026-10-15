"""Lobby API + universe entry."""
from __future__ import annotations

import json
import re
import time

from playwright.sync_api import BrowserContext, Page

from .browser import wait_captcha
from .models import LogFn, _noop

def _accept_cookies(page: Page) -> None:
    try:
        page.get_by_role("button", name=re.compile("Accept Cookies", re.I)).click(timeout=3000)
    except Exception:
        pass


def _ingame(page: Page) -> bool:
    u = page.url or ""
    return "page=ingame" in u or "/game/index.php" in u


def _game_host(context: BrowserContext) -> str | None:
    for c in context.cookies():
        d = (c.get("domain") or "").lstrip(".")
        if re.fullmatch(r"s\d+[-\w]*\.ogame\.gameforge\.com", d):
            return d
    return None


def _lobby_token(context: BrowserContext) -> str | None:
    for c in context.cookies():
        if c.get("name") == "gf-token-production" and c.get("value"):
            return c["value"]
    return None


def _resolve_server(
    servers: list, uni: str, lang: str | None
) -> dict | None:
    """Map universe name (or number) → server entry; prefer Language."""
    uni_l = uni.strip().lower()
    lang_l = (lang or "").strip().lower() or None
    hits = [
        s
        for s in servers
        if isinstance(s, dict)
        and (
            str(s.get("name", "")).lower() == uni_l
            or str(s.get("number", "")) == uni_l
        )
    ]
    if lang_l:
        by_lang = [s for s in hits if str(s.get("language", "")).lower() == lang_l]
        if by_lang:
            return by_lang[0]
    return hits[0] if hits else None


def _find_account(accs: list, server: dict) -> dict | None:
    """Accounts payload has server.{language,number} only — no name."""
    want_lang = str(server.get("language", "")).lower()
    want_num = int(server.get("number", -1))
    for a in accs:
        if not isinstance(a, dict):
            continue
        srv = a.get("server") or {}
        if (
            str(srv.get("language", "")).lower() == want_lang
            and int(srv.get("number", -2)) == want_num
        ):
            return a
    return None


def _account_labels(accs: list, servers: list) -> str:
    by_key = {
        (str(s.get("language", "")).lower(), int(s.get("number", -1))): s.get("name")
        for s in servers
        if isinstance(s, dict)
    }
    parts = []
    for a in accs:
        if not isinstance(a, dict):
            continue
        srv = a.get("server") or {}
        key = (str(srv.get("language", "")).lower(), int(srv.get("number", -1)))
        name = by_key.get(key) or "?"
        parts.append(f"{name} ({key[0]}-{key[1]})")
    return ", ".join(parts) or "(nenhuma)"


def _server_host(server: dict) -> str:
    return f"s{server['number']}-{server['language']}.ogame.gameforge.com"


def _lobby_locale(lang: str) -> str:
    return {"br": "pt_BR", "pt": "pt_PT", "us": "en_US"}.get(
        (lang or "br").lower(), "en_GB"
    )


def _fetch_servers_accounts(req, lobby: str, hdr: dict) -> tuple[list, list]:
    servers = req.get(
        f"https://{lobby}.ogame.gameforge.com/api/servers", headers=hdr
    ).json()
    if not isinstance(servers, list):
        raise RuntimeError(f"servers api: {servers}")
    accs = req.get(
        f"https://{lobby}.ogame.gameforge.com/api/users/me/accounts", headers=hdr
    ).json()
    if not isinstance(accs, list):
        raise RuntimeError(f"accounts api: {accs}")
    return servers, accs


def _add_account(req, lobby: str, hdr: dict, account_group: str, locale: str) -> dict:
    """Join universe from server listing (not in hub shortcuts yet)."""
    data = req.put(
        f"https://{lobby}.ogame.gameforge.com/api/users/me/accounts",
        headers={**hdr, "Content-Type": "application/json"},
        data=json.dumps(
            {"accountGroup": account_group, "locale": locale, "kid": ""}
        ),
    ).json()
    if not isinstance(data, dict) or not data.get("id"):
        raise RuntimeError(f"listagem: criar conta falhou: {data}")
    return data


def _login_link(req, lobby: str, hdr: dict, acc: dict) -> str | None:
    """POST loginLink; GET fallback. None se API recusar (ex. sem blackbox → [])."""
    lang = acc["server"]["language"]
    num = int(acc["server"]["number"])
    aid = int(acc["id"])
    payload = {
        "server": {"language": lang, "number": num},
        "id": aid,
        "clickedButton": "account_list",
    }
    data = req.post(
        f"https://{lobby}.ogame.gameforge.com/api/users/me/loginLink",
        headers={**hdr, "Content-Type": "application/json"},
        data=json.dumps(payload),
    ).json()
    url = data.get("url") or data.get("URL") if isinstance(data, dict) else None
    if not url:
        data = req.get(
            f"https://{lobby}.ogame.gameforge.com/api/users/me/loginLink"
            f"?id={aid}&server[language]={lang}&server[number]={num}",
            headers=hdr,
        ).json()
        url = data.get("url") or data.get("URL") if isinstance(data, dict) else None
    if not url:
        return None
    if url.startswith("/"):
        url = f"https://{lobby}.ogame.gameforge.com{url}"
    return url


def _lobby_dom_debug(page: Page) -> dict:
    """O que o hub realmente mostra: textos perto de Play + body snippet."""
    return page.evaluate(
        """() => {
          const playRe = /^(play|jogar)$/i;
          const near = [];
          for (const btn of document.querySelectorAll('button, a')) {
            const t = (btn.innerText || btn.textContent || '').trim();
            if (!playRe.test(t)) continue;
            let n = btn.parentElement;
            for (let i = 0; i < 6 && n; i++, n = n.parentElement) {
              const txt = (n.innerText || '').replace(/\\s+/g, ' ').trim();
              if (txt && txt.length < 400) { near.push(txt.slice(0, 200)); break; }
            }
          }
          const headings = [...document.querySelectorAll('h1,h2,h3,h4,[class*="server"],[class*="account"],[class*="universe"]')]
            .map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim())
            .filter(Boolean)
            .slice(0, 40);
          const body = (document.body && document.body.innerText || '')
            .replace(/\\s+/g, ' ').trim().slice(0, 800);
          return {
            url: location.href,
            playRows: [...new Set(near)].slice(0, 20),
            headings: [...new Set(headings)].slice(0, 30),
            body: body,
          };
        }"""
    )


def _lobby_base(lobby: str, lang: str = "br") -> str:
    """UI locale path from community (br→pt_BR). Hub atalho ≠ listagem."""
    return f"https://{lobby}.ogame.gameforge.com/{_lobby_locale(lang)}"


# rótulos/aliases do filtro de comunidade no /accounts
_LANG_ALIASES: dict[str, tuple[str, ...]] = {
    "br": ("br", "brazil", "brasil", "brazilian", "português", "portuguese"),
    "pt": ("pt", "portugal", "português", "portuguese"),
    "en": ("en", "gb", "uk", "english"),
    "us": ("us", "usa", "american", "english"),
    "de": ("de", "german", "deutsch", "germany"),
    "es": ("es", "spanish", "español", "spain"),
    "fr": ("fr", "french", "français", "france"),
    "hu": ("hu", "hungarian", "magyar"),
    "nl": ("nl", "dutch", "nederlands"),
    "pl": ("pl", "polish", "polski"),
    "tr": ("tr", "turkish", "türk"),
    "it": ("it", "italian", "italiano"),
    "ru": ("ru", "russian", "русский"),
}


def _lang_aliases(lang: str) -> tuple[str, ...]:
    lang = (lang or "br").lower()
    return _LANG_ALIASES.get(lang, (lang,))


def _select_server_language(page: Page, lang: str, log: LogFn) -> None:
    """Ativa o filtro de comunidade/idioma na listagem /servers."""
    lang_l = (lang or "br").lower()
    aliases = _lang_aliases(lang_l)
    log(f"filtro idioma listagem: {lang_l}", "warn")

    # 1) select nativo
    for sel in page.locator("select").all():
        try:
            opts = sel.locator("option")
            for i in range(opts.count()):
                o = opts.nth(i)
                val = (o.get_attribute("value") or "").lower()
                txt = (o.inner_text() or "").lower()
                if any(a == val or a in txt for a in aliases):
                    sel.select_option(value=o.get_attribute("value") or None)
                    page.wait_for_timeout(700)
                    return
        except Exception:
            continue

    # 2) botão/flag/data-attr
    for a in aliases:
        for sel in (
            f'[data-language="{a}"]',
            f'[data-lang="{a}"]',
            f'button[value="{a}"]',
            f'img[alt="{a}" i]',
            f'img[src*="/{a}." i]',
            f'img[src*="/{a}_" i]',
            f'img[src*="_{a}_" i]',
            f'img[src*="flag/{a}" i]',
            f'img[src*="flags/{a}" i]',
            f'[class*="flag"][class*="{a}"]',
            f'button:has-text("{a.upper()}")',
            f'button:has-text("{a}")',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=500):
                    loc.click()
                    page.wait_for_timeout(700)
                    return
            except Exception:
                continue

    # 3) role=option / menuitem com alias
    for a in aliases:
        try:
            opt = page.get_by_role(
                "option", name=re.compile(rf"^{re.escape(a)}$|{re.escape(a)}", re.I)
            )
            if opt.count() and opt.first.is_visible(timeout=400):
                opt.first.click()
                page.wait_for_timeout(700)
                return
        except Exception:
            continue

    log(f"filtro idioma '{lang_l}' não clicado — seguindo sem filtro UI", "warn")


def _open_accounts_list(page: Page, lobby: str, lang: str, log: LogFn) -> None:
    """Hub só mostra último jogado; contas (ex. Dione) ficam em /accounts."""
    lang_l = (lang or "br").lower()
    url = f"{_lobby_base(lobby, lang_l)}/accounts"
    log(f"abrindo contas: {url}", "warn")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    _accept_cookies(page)
    _select_server_language(page, lang_l, log)


def _play_ui(
    page: Page,
    uni: str,
    log: LogFn,
    timeout_ms: int,
    *,
    lobby: str = "lobby",
    lang: str = "br",
) -> Page:
    """Ignora atalho 'último servidor'; abre /accounts e clica Jogar no uni."""
    lang_l = (lang or "br").lower()
    log(f"loginLink vazio — /accounts ({uni}/{lang_l})", "warn")
    _open_accounts_list(page, lobby, lang_l, log)

    play_re = re.compile(r"^(Play|Jogar)$", re.I)

    # busca na listagem
    try:
        box = page.locator(
            'input[type="search"], input[placeholder*="earch" i], '
            'input[placeholder*="uscar" i], input[placeholder*="ilter" i]'
        ).first
        if box.count() and box.is_visible(timeout=800):
            box.fill(uni)
            page.wait_for_timeout(800)
    except Exception:
        pass

    dbg = _lobby_dom_debug(page)
    log(
        f"accounts DOM lang={lang_l} url={dbg.get('url')} | "
        f"playRows={dbg.get('playRows')} | headings={dbg.get('headings')}",
        "warn",
    )
    log(f"accounts body≈ {dbg.get('body')}", "warn")

    # Jogar cujo row (ancestral com 1 Play) contém o nome do uni — não a página toda
    btns = page.locator("button, a").filter(has_text=play_re)
    btn = None
    for i in range(btns.count()):
        b = btns.nth(i)
        try:
            if not b.is_visible(timeout=300):
                continue
        except Exception:
            continue
        near = b.evaluate(
            """(el, uni) => {
              const uniRe = new RegExp(
                '\\\\b' + uni.replace(/[.*+?^${}()|[\\\\]\\\\]/g, '\\\\$&') + '\\\\b', 'i'
              );
              const playRe = /^(play|jogar)$/i;
              let n = el.parentElement;
              for (let d = 0; d < 12 && n; d++, n = n.parentElement) {
                const txt = (n.innerText || '').replace(/\\s+/g, ' ').trim();
                if (!uniRe.test(txt)) continue;
                const plays = [...n.querySelectorAll('button, a')].filter(x =>
                  playRe.test((x.innerText || x.textContent || '').trim())
                );
                // row da conta: exatamente 1 Jogar (= este). Página/tabela tem vários.
                if (plays.length === 1 && plays[0] === el) return true;
              }
              return false;
            }""",
            uni,
        )
        if near:
            btn = b
            break

    if btn is None:
        raise RuntimeError(
            f"listagem: Play ausente p/ '{uni}' ({lang_l}); "
            f"playRows={dbg.get('playRows')}; headings={dbg.get('headings')}"
        )

    try:
        with page.context.expect_page(timeout=min(15_000, timeout_ms)) as pi:
            btn.click()
        game = pi.value
    except Exception:
        btn.click()
        game = page
    return _wait_ingame(page, game, log, timeout_ms)


def _wait_ingame(
    page: Page, game: Page, log: LogFn, timeout_ms: int
) -> Page:
    end = time.time() + timeout_ms / 1000
    while time.time() < end and not _ingame(game):
        _accept_cookies(game)
        left = int((end - time.time()) * 1000)
        if left > 500:
            wait_captcha(game, log, timeout_ms=min(30_000, left))
        for p in page.context.pages:
            if _ingame(p):
                return p
        game.wait_for_timeout(200)
    return game


def _assert_universe(game: Page, server: dict, uni: str) -> None:
    want = _server_host(server)
    host = re.search(r"https?://([^/]+)", game.url or "")
    got = (host.group(1) if host else "") or ""
    if got != want:
        raise RuntimeError(
            f"universo errado: entrou em {got or game.url!r}, queria {uni} ({want})"
        )


def _enter_universe(
    page: Page, cred: dict, log: LogFn = _noop, *, timeout_ms: int = 90_000
) -> Page:
    """Hub shortcut (accounts) → senão listagem de servers (join) → jogo."""
    lobby = cred.get("Lobby") or "lobby"
    uni = cred["Universe"]
    lang = cred.get("Language") or "br"
    token = _lobby_token(page.context)
    if not token:
        raise RuntimeError("sem token lobby (gf-token-production)")

    hdr = {"Authorization": f"Bearer {token}"}
    req = page.context.request
    servers, accs = _fetch_servers_accounts(req, lobby, hdr)
    server = _resolve_server(servers, uni, lang)
    if not server:
        raise RuntimeError(f"universo '{uni}' (lang={lang}) não existe no lobby")

    acc = _find_account(accs, server)
    if acc:
        log(f"atalho ok: {uni}", "ok")
    else:
        # não está nos atalhos/contas → listagem (PUT cria conta no uni)
        group = server.get("accountGroup") or f"{server['language']}_{server['number']}"
        log(f"sem atalho {uni} — entrando pela listagem ({group})", "warn")
        created = _add_account(req, lobby, hdr, group, _lobby_locale(lang))
        acc = {
            "id": created["id"],
            "server": created.get("server")
            or {"language": server["language"], "number": server["number"]},
        }

    url = _login_link(req, lobby, hdr, acc)
    if url:
        game = page.context.new_page()
        game.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        game = _wait_ingame(page, game, log, timeout_ms)
    else:
        log(f"API contas: {_account_labels(accs, servers)}", "warn")
        game = _play_ui(
            page, uni, log, timeout_ms, lobby=lobby, lang=lang
        )

    if not _ingame(game):
        raise RuntimeError(f"Play não abriu o jogo em {timeout_ms}ms ({game.url})")
    _assert_universe(game, server, uni)

    wait_captcha(game, log)
    game.wait_for_selector("#resources_metal", timeout=90_000)
    log(f"entrou no jogo ({uni} / {_server_host(server)})", "ok")
    return game
