"""Fingerprint, launch, captcha, visibility swap."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, Playwright, Route

from .models import LogFn, _noop

# package = game/; session files stay at repo root
ROOT = Path(__file__).resolve().parent.parent

# Keep document/script/stylesheet/xhr/fetch — parsing + game JS depend on them.
_BLOCK_TYPES = frozenset({"font", "media"})

# ponytail: chrome flags only; tighter (single-process / block CSS) if RAM still high
_LEAN_ARGS = (
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
    "--disable-default-apps",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-breakpad",
    "--disable-sync",
    "--disable-translate",
    "--disable-domain-reliability",
    "--disable-client-side-phishing-detection",
    "--disable-features=TranslateUI,InterestFeedContentSuggestions",
    "--disable-dev-shm-usage",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--no-default-browser-check",
)


def session_path(device_conf: dict) -> Path:
    name = (device_conf.get("Name") or "default").replace(" ", "_")
    return ROOT / f"session_{name}.json"


def save_session(context: BrowserContext, path: Path) -> None:
    context.storage_state(path=str(path))


def _lean_route(route: Route) -> None:
    if route.request.resource_type in _BLOCK_TYPES:
        route.abort()
    else:
        route.continue_()


def apply_device(context: BrowserContext, conf: dict) -> None:
    """Consistent fingerprint via Playwright context + navigator overrides."""
    ua = conf.get("UserAgent") or None
    width = int(conf.get("Width") or 1920)
    height = int(conf.get("Height") or 1080)
    tz = conf.get("Timezone") or "America/Sao_Paulo"
    lang = conf.get("Lang") or "pt-BR"
    memory = int(conf.get("Memory") or 8)
    concurrency = int(conf.get("Concurrency") or 16)
    color = int(conf.get("Color") or 24)

    context.set_extra_http_headers({"Accept-Language": f"{lang},en;q=0.9"})
    context.add_init_script(
        f"""
        Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {memory} }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {concurrency} }});
        Object.defineProperty(screen, 'colorDepth', {{ get: () => {color} }});
        Object.defineProperty(screen, 'pixelDepth', {{ get: () => {color} }});
        """
    )
    context.route("**/*", _lean_route)
    context._device_conf = {  # type: ignore[attr-defined]
        "user_agent": ua,
        "viewport": {"width": width, "height": height},
        "timezone_id": tz,
        "locale": lang.replace("_", "-"),
    }


def new_context(
    browser,
    conf: dict,
    storage_state: Path | str | dict[str, Any] | None = None,
) -> BrowserContext:
    kwargs: dict[str, Any] = {
        "viewport": {
            "width": int(conf.get("Width") or 1920),
            "height": int(conf.get("Height") or 1080),
        },
        "locale": (conf.get("Lang") or "pt-BR").replace("_", "-"),
        "timezone_id": conf.get("Timezone") or "America/Sao_Paulo",
    }
    if conf.get("UserAgent"):
        kwargs["user_agent"] = conf["UserAgent"]
    if isinstance(storage_state, dict):
        kwargs["storage_state"] = storage_state
    elif storage_state and Path(storage_state).exists():
        kwargs["storage_state"] = str(storage_state)
    ctx = browser.new_context(**kwargs)
    apply_device(ctx, conf)
    return ctx


def launch_browser(p: Playwright, headless: bool = False):
    args = list(_LEAN_ARGS)
    if headless:
        # images off only headless — headed needs captcha / inspect pixels
        args.extend(
            (
                "--disable-gpu",
                "--disable-gpu-compositing",
                "--blink-settings=imagesEnabled=false",
            )
        )
    kwargs: dict[str, Any] = {"headless": headless, "args": args}
    try:
        return p.chromium.launch(channel="chrome", **kwargs)
    except Exception:
        return p.chromium.launch(**kwargs)


def close_browser(browser) -> None:
    """Best-effort; DOM morto ≠ processo morto — sempre tentar antes de relaunch."""
    if not browser:
        return
    try:
        browser.close()
    except Exception:
        pass


def wait_captcha(page: Page, log: LogFn = _noop, timeout_ms: int = 180_000) -> None:
    """Pause if captcha iframe/widget visible; manual resolve only (API later)."""
    selectors = (
        "iframe[src*='captcha']",
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        ".g-recaptcha",
        "#captcha",
        "[data-captcha]",
    )
    for sel in selectors:
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                log("captcha detectado — resolva na janela do browser", "warn")
                page.wait_for_selector(sel, state="hidden", timeout=timeout_ms)
                log("captcha ok", "ok")
                return
        except Exception:
            continue


def browser_alive(page: Page) -> bool:
    """True se o Chromium ainda está de pé. Mid-navigation ≠ morto."""
    try:
        browser = page.context.browser
        if browser is None or not browser.is_connected():
            return False
        if page.is_closed():
            return False
        page.evaluate("1")
        return True
    except Exception as e:
        err = str(e).lower()
        if any(
            s in err
            for s in ("navigat", "execution context", "destroyed", "cannot find context")
        ):
            try:
                b = page.context.browser
                return b is not None and b.is_connected() and not page.is_closed()
            except Exception:
                return False
        return False


def _swap_visibility(
    p: Playwright, game: Page, conf: dict, *, headless: bool, log: LogFn = _noop
) -> Page:
    """Relaunch same cookies/URL as headed or headless. Caller must save_session first."""
    url = game.url
    state = game.context.storage_state()
    close_browser(game.context.browser)
    browser = launch_browser(p, headless=headless)
    page = new_context(browser, conf, storage_state=state).new_page()
    page.goto(url, wait_until="domcontentloaded")
    if headless:
        page.wait_for_selector("#resources_metal", timeout=90_000)
    return page


def go_headless(p: Playwright, game: Page, conf: dict, log: LogFn = _noop) -> Page:
    page = _swap_visibility(p, game, conf, headless=True, log=log)
    log("headless on", "ok")
    return page


def go_headed(p: Playwright, game: Page, conf: dict, log: LogFn = _noop) -> Page:
    page = _swap_visibility(p, game, conf, headless=False, log=log)
    log("browser visível — workers pausados (b ou feche a janela p/ voltar)", "warn")
    return page
