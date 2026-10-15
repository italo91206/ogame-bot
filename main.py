"""Login → runtime loop. Ctrl+C sair. b=browser r=reconfirm."""
from __future__ import annotations

import time

from playwright.sync_api import sync_playwright

from compose import build_runtime
from config import load_settings
from game import (
    ResourceBook,
    browser_alive,
    close_browser,
    dom_health,
    go_headed,
    go_headless,
    launch_browser,
    login,
    new_context,
    parse_celestials,
    resume_session,
    revive_headless,
    save_session,
    session_path,
)
from keys import KeyPump
from features.overview import worker_rows
from runtime import Worker
from telegram_notify import from_settings as telegram_from_settings
from tui import SHORTCUTS_INSPECT, SHORTCUTS_RUN, BotTUI, WorkerRow
from tui_boot import play_boot

_DASH = "dash"


def main() -> None:
    settings = load_settings()
    cred = settings["Credentials"]
    general = settings["General"]
    leave = int(general.get("SlotsToLeaveFree") or 1)
    headless = bool(general.get("Headless"))
    uni = cred["Universe"]

    tui = BotTUI(universe=uni)
    dom_health.boot()
    tui.set_status("boot")

    runtime = build_runtime(settings)
    stubs: list[WorkerRow] = []
    tui.set_workers(worker_rows(runtime.workers, stubs))

    with tui.live() as live:
        play_boot(tui, live, universe=uni)
        tui.set_status("login")
        tui.log("iniciando browser" + (" headless" if headless else ""))
        live.update(tui.render())

        def tick(msg: str | None = None, level: str = "info") -> None:
            if msg:
                tui.log(msg, level)
            live.update(tui.render())

        with sync_playwright() as p:
            device = cred.get("DeviceConf") or {}
            spath = session_path(device)
            # sessao válida → pode ir headless direto; senão janela p/ captcha
            start_headless = bool(headless and spath.exists())
            browser = launch_browser(p, headless=start_headless)
            if headless and not start_headless:
                tick("janela aberta p/ login — headless depois", "warn")
            game = None
            resumed = False

            try:
                log = lambda m, lv="info": tick(m, lv)
                if spath.exists():
                    context = new_context(browser, device, storage_state=spath)
                    page = context.new_page()
                    game = resume_session(page, cred, log=log)
                    resumed = game is not None
                    if not resumed:
                        context.close()
                tg = telegram_from_settings(
                    settings, log=lambda m, lv="info": tui.log(m, lv)
                )

                # ponytail: ganchos de humano via strings do game/ — upgrade: callback on_captcha
                _NEED_HUMAN = (
                    "aguardando login (resolva captcha",
                    "captcha detectado",
                )

                def log(m: str, lv: str = "info") -> None:
                    tick(m, lv)
                    if any(h in m for h in _NEED_HUMAN):
                        tg.notify(
                            "precisa humano no desktop: login/captcha — "
                            "depois b ou /resume",
                            key="login_captcha",
                            cooldown_s=300,
                        )

                if not resumed:
                    if start_headless:
                        close_browser(browser)
                        browser = launch_browser(p, headless=False)
                        tick("sessão inválida — janela p/ login", "warn")
                        tg.notify(
                            "sessão inválida — janela p/ login no desktop",
                            key="login",
                        )
                    context = new_context(browser, device)
                    page = context.new_page()
                    game = login(page, cred, log=log)
                save_session(game.context, spath)
                if headless and not start_headless:
                    game = go_headless(p, game, device, log=log)
                    browser = game.context.browser
                    save_session(game.context, spath)
                parse_celestials(game)  # marca last_good se planetList ok
                tui.set_status("running")
                tick(None)

                ctx = {
                    "page": game,
                    "tui": tui,
                    "settings": settings,
                    "slots_to_leave_free": leave,
                    "runtime": runtime,
                    "resources": ResourceBook(),
                    "notify": tg.notify,
                }

                def on_idle() -> None:
                    ctx["resources"].push_tui(tui)
                    tui.health = dom_health.status_line()
                    tui.set_workers(worker_rows(runtime.workers, stubs))
                    if tui.view == "logs":
                        tui.show_log_tail(50)
                    live.update(tui.render())

                ctx["refresh"] = on_idle

                inspecting = False
                recovering = False
                paused: list[Worker] = []
                last_dom_crit_log = 0.0
                # nomes ativos no boot — heal se pause aninhado perder a lista
                boot_active = {w.name for w in runtime.workers if w.active}

                def pause_workers() -> None:
                    # ponytail: não clear se já pausado — recover após inspect
                    # apagava a lista e deixava todos active=False p/ sempre
                    # Defender fica up (paridade SleepMode / TBot) — anti-ataque
                    if paused:
                        return
                    for w in runtime.workers:
                        if w.active and w.name != "Defender":
                            paused.append(w)
                            w.active = False

                def resume_workers() -> None:
                    if paused:
                        for w in paused:
                            w.active = True
                        paused.clear()
                    elif not any(w.active for w in runtime.workers):
                        for w in runtime.workers:
                            if w.name in boot_active:
                                w.active = True

                def recover_dead_dom() -> None:
                    """Sessão/DOM mortos → browser headed + resume/login."""
                    nonlocal game, browser, recovering, inspecting
                    if inspecting or recovering:
                        return
                    recovering = True
                    pause_workers()
                    tick("DOM morto — abrindo browser p/ login", "warn")
                    try:
                        # DOM morto ≠ chromium morto — fechar sempre antes do relaunch
                        old = browser
                        try:
                            if game:
                                try:
                                    save_session(game.context, spath)
                                except Exception:
                                    pass
                                old = game.context.browser or browser
                        except Exception:
                            pass
                        close_browser(old)
                        browser = launch_browser(p, headless=False)
                        game = None
                        if spath.exists():
                            context = new_context(browser, device, storage_state=spath)
                            page = context.new_page()
                            game = resume_session(page, cred, log=log)
                            if game is None:
                                context.close()
                        if game is None:
                            context = new_context(browser, device)
                            page = context.new_page()
                            game = login(page, cred, log=log)
                        save_session(game.context, spath)
                        ctx["page"] = game
                        if parse_celestials(game):
                            if headless:
                                game = go_headless(p, game, device, log=log)
                                browser = game.context.browser
                                save_session(game.context, spath)
                                ctx["page"] = game
                                parse_celestials(game)  # heartbeat no page novo
                            for w in runtime.workers:
                                w._next_at = 0.0
                            resume_workers()
                            tick("DOM ok — bot retomado", "ok")
                        else:
                            inspecting = True
                            tui.shortcuts = SHORTCUTS_INSPECT
                            tui.set_status("inspect · login incompleto — b quando ok")
                            tick("login incompleto — resolva e aperte b", "warn")
                            tg.notify(
                                "login incompleto — no desktop: login, depois b ou /resume",
                                key="login_incomplete",
                            )
                    except Exception as e:
                        tick(f"recover falhou ({e}) — janela aberta se possível", "warn")
                        inspecting = True
                        tui.shortcuts = SHORTCUTS_INSPECT
                        tui.set_status("inspect · resolve login e aperte b")
                        tg.notify(
                            f"recover falhou ({e}) — no desktop: resolva login",
                            key="recover_fail",
                            cooldown_s=60,
                        )
                    finally:
                        recovering = False

                tg.commands.update(
                    {
                        "/ping": lambda: f"pong · {tg.uptime()}",
                        "/status": lambda: (
                            f"uptime {tg.uptime()}\n"
                            f"headless={headless} inspect={inspecting} "
                            f"recover={recovering}\n"
                            f"workers on="
                            f"{sum(1 for w in runtime.workers if w.active)}/"
                            f"{len(runtime.workers)}\n"
                            f"health {dom_health.status_line()}\n"
                            + (
                                f"SOB ATAQUE ×{tui.under_attack_n or 1}: "
                                f"{tui.under_attack}"
                                if tui.under_attack
                                else "ataque: safe"
                            )
                        ),
                        "/pause": lambda: (
                            "já em inspect/recover"
                            if inspecting or recovering
                            else (pause_workers() or "workers pausados")
                        ),
                        "/resume": lambda: (
                            "inspect — no desktop: tecla b"
                            if inspecting
                            else "recover em andamento"
                            if recovering
                            else (
                                (resume_workers() or "workers retomados")
                                if paused
                                else "nada pausado"
                            )
                        ),
                    }
                )
                tg.start()
                tg.notify(f"bot up · {uni} · {tg.uptime()}", key="boot", cooldown_s=30)
                if not tg.chat_id:
                    tick("telegram: envie /start no bot p/ ligar o chat", "warn")

                def enter_inspect() -> None:
                    nonlocal game, inspecting
                    save_session(game.context, spath)
                    pause_workers()
                    if headless:
                        try:
                            game = go_headed(p, game, device, log=log)
                            browser = game.context.browser
                            ctx["page"] = game
                        except Exception as e:
                            tick(f"abrir browser falhou ({e}) — revive", "warn")
                            game = revive_headless(
                                p, device, spath, cred, log=log
                            )
                            ctx["page"] = game
                            resume_workers()
                            return
                    else:
                        tick(
                            "workers pausados — navegue; b p/ retomar",
                            "warn",
                        )
                    inspecting = True
                    tui.shortcuts = SHORTCUTS_INSPECT
                    tui.set_status("inspect · b ou feche a janela p/ voltar")

                def leave_inspect() -> None:
                    nonlocal game, inspecting
                    alive = browser_alive(game)
                    if headless or not alive:
                        try:
                            if alive:
                                save_session(game.context, spath)
                                game = go_headless(p, game, device, log=log)
                                browser = game.context.browser
                            else:
                                tick("janela fechada — voltando headless", "warn")
                                try:
                                    close_browser(game.context.browser)
                                except Exception:
                                    close_browser(browser)
                                game = revive_headless(
                                    p, device, spath, cred, log=log
                                )
                                browser = game.context.browser
                            save_session(game.context, spath)
                            ctx["page"] = game
                            parse_celestials(game)  # evita is_stale imediato pós-inspect longo
                        except Exception as e:
                            tick(f"voltar headless falhou ({e}) — recover", "warn")
                            inspecting = False
                            recover_dead_dom()
                            return
                    inspecting = False
                    resume_workers()
                    tui.shortcuts = SHORTCUTS_RUN
                    tui.set_status("running")
                    tick("bot retomado", "ok")

                keys = KeyPump()
                keys.start()
                try:
                    while True:
                        # janela fechada antes de tecla — evita b bufferizado reabrir inspect
                        if inspecting and not browser_alive(game):
                            leave_inspect()
                            keys.drain()
                            on_idle()
                        else:
                            key = keys.get()
                            sc = SHORTCUTS_INSPECT if inspecting else SHORTCUTS_RUN
                            if key == "l":
                                if tui.view == "logs":
                                    tui.hide_overlay(sc)
                                else:
                                    tui.show_log_tail(50)
                                keys.drain()
                                on_idle()
                            elif key == "w":
                                if tui.view == "workers":
                                    tui.hide_overlay(sc)
                                else:
                                    tui.show_workers()
                                keys.drain()
                                on_idle()
                            elif key == "b" and tui.view == _DASH:
                                if inspecting:
                                    leave_inspect()
                                else:
                                    enter_inspect()
                                keys.drain()
                                on_idle()
                            elif key == "r" and not inspecting and tui.view == _DASH:
                                tick("reconfirm — tick em todos os workers", "warn")
                                keys.drain()
                                for name, status in runtime.reconfirm(
                                    ctx, stop_when=keys.has_interrupt
                                ):
                                    tick(f"{name}: {status}", "ok")
                                on_idle()
                            # overlays (l/w) só mudam a TUI — workers e health seguem
                            elif dom_health.is_critical_stale():
                                sg = dom_health.since_good()
                                age = (
                                    f"{int(sg // 60)}m"
                                    if sg is not None
                                    else "nunca"
                                )
                                msg = (
                                    f"DOM crítico ({age}) — bot down, ação no desktop"
                                )
                                now = time.time()
                                if now - last_dom_crit_log >= 30 * 60:
                                    last_dom_crit_log = now
                                    tick(msg, "warn")
                                    tg.notify(
                                        msg, key="dom_critical", cooldown_s=0
                                    )
                                if not inspecting:
                                    recover_dead_dom()
                            elif not inspecting:
                                if dom_health.is_stale():
                                    recover_dead_dom()
                                else:
                                    for name, status in runtime.run_once(
                                        ctx, stop_when=keys.has_interrupt
                                    ):
                                        tick(f"{name}: {status}", "ok")
                        on_idle()
                        # pending key / inspect → poll curto; overlay não pausa o bot
                        if keys.pending() or inspecting:
                            time.sleep(0.05)
                        else:
                            time.sleep(1)
                except KeyboardInterrupt:
                    tui.set_status("stopped")
                    tick("Ctrl+C — saindo", "warn")
                    tg.notify("bot parando (Ctrl+C)", key="stop", cooldown_s=5)
                    live.update(tui.render())
                    time.sleep(0.5)
                finally:
                    keys.stop()
                    tg.stop()
            finally:
                try:
                    cur = game.context.browser if game else None
                except Exception:
                    cur = None
                close_browser(cur)
                if browser is not None and browser is not cur:
                    close_browser(browser)


if __name__ == "__main__":
    main()
