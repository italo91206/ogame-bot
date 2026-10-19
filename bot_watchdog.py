"""Watchdog Telegram: alerta se o heartbeat do bot parar (kill / crash duro).

Roda em processo separado — o main sobe um detached no boot.
Uso manual: python bot_watchdog.py

Single-instance via lock file (pid file sozinho raceava → N órfãos).
Saída graciosa (CLEAN_STOP) ou Active=false → processo termina (não fica zombie).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from config import load_settings
from telegram_notify import CLEAN_STOP, HEARTBEAT, from_settings, heartbeat_age_s

ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / "logs" / "watchdog.pid"
LOCK_FILE = ROOT / "logs" / "watchdog.lock"
_SCRIPT = str((ROOT / "bot_watchdog.py").resolve())


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _already_running() -> bool:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if pid == os.getpid():
        return False
    return _pid_alive(pid)


def _write_pid() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")


def _try_lock() -> int | None:
    """Lock exclusivo; segura o fd aberto. None se outra instância já segura."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
    except OSError:
        pass
    return fd


def _release_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _list_watchdog_pids() -> list[int]:
    """PIDs de bot_watchdog.py deste ROOT (best-effort)."""
    me = os.getpid()
    marker = _SCRIPT.lower()
    found: list[int] = []
    if sys.platform == "win32":
        try:
            # Escape single quotes for PowerShell string
            m = marker.replace("'", "''")
            ps = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -and "
                f"($_.CommandLine.ToLower().Contains('{m}')) }} | "
                "Select-Object -ExpandProperty ProcessId"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=45,
                cwd=str(ROOT),
            )
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    if pid != me:
                        found.append(pid)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return found
    # POSIX: /proc
    try:
        for ent in Path("/proc").iterdir():
            if not ent.name.isdigit():
                continue
            pid = int(ent.name)
            if pid == me:
                continue
            try:
                cmdline = (ent / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
                    "utf-8", "replace"
                )
            except OSError:
                continue
            if marker in cmdline.lower():
                found.append(pid)
    except OSError:
        pass
    return found


def kill_orphan_watchdogs(*, log=None) -> int:
    """Mata outras instâncias deste script. Retorna quantas matou."""
    n = 0
    for pid in _list_watchdog_pids():
        try:
            if sys.platform == "win32":
                r = subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    timeout=15,
                )
                if r.returncode == 0:
                    n += 1
            else:
                os.kill(pid, 9)
                n += 1
        except (OSError, subprocess.SubprocessError):
            continue
    if n and log:
        log(f"watchdog: matou {n} órfão(s)", "warn")
    return n


def _watchdog_wanted(settings: dict) -> bool:
    wd = settings.get("TelegramWatchdog") or {}
    tg = settings.get("TelegramMessenger") or {}
    if not wd.get("Active", True):
        return False
    if not tg.get("Active", True):
        return False
    return True


def ensure_watchdog(*, log=None) -> bool:
    """Sobe watchdog detached se settings Active e nenhum vivo. Retorna se spawnou."""
    settings = load_settings()
    if not _watchdog_wanted(settings):
        return False
    if _already_running():
        # lock real: se pid file mente, limpa órfãos e tenta de novo
        if log:
            log("watchdog: já rodando", "info")
        return False
    # Antes do spawn: zera órfãos do race antigo (pid file só guarda 1)
    kill_orphan_watchdogs(log=log)
    kwargs: dict = {
        "args": [sys.executable, str(ROOT / "bot_watchdog.py")],
        "cwd": str(ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        # DETACHED + novo group: sobrevive se o main morrer / console fechar
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(**kwargs)
    if log:
        log("watchdog: iniciado (detached)", "ok")
    return True


def main() -> None:
    lock_fd = _try_lock()
    if lock_fd is None:
        print("watchdog já rodando (lock)", file=sys.stderr)
        return
    _write_pid()
    try:
        settings = load_settings()
        if not _watchdog_wanted(settings):
            print(
                "watchdog: TelegramWatchdog/Messenger inativo — saindo",
                file=sys.stderr,
            )
            return
        wd = settings.get("TelegramWatchdog") or {}
        stale_s = float(wd.get("StaleMinutes") or 5) * 60
        check_s = float(wd.get("CheckEverySeconds") or 30)
        alert_cd = float(wd.get("AlertCooldownMinutes") or 30) * 60
        tg = from_settings(settings, log=lambda m, lv="info": print(f"[{lv}] {m}"))
        if not tg.active or not tg.chat_id:
            print(
                "watchdog: Telegram inativo / sem chat_id — saindo",
                file=sys.stderr,
            )
            return

        print(
            f"watchdog up · stale>{stale_s:.0f}s · check {check_s:.0f}s · pid {os.getpid()}"
        )
        # Clean stop já presente no boot = bot não está up; não vigiar
        if CLEAN_STOP.exists() and not (
            HEARTBEAT.exists()
            and (heartbeat_age_s() or 9999) <= stale_s
        ):
            print("watchdog: clean stop sem bot vivo — saindo", file=sys.stderr)
            return

        saw_alive = HEARTBEAT.exists() and not CLEAN_STOP.exists()
        last_alert = 0.0
        while True:
            settings = load_settings()
            if not _watchdog_wanted(settings):
                print("watchdog: Active=false — saindo")
                break
            wd = settings.get("TelegramWatchdog") or {}
            stale_s = float(wd.get("StaleMinutes") or 5) * 60
            check_s = float(wd.get("CheckEverySeconds") or 30)
            alert_cd = float(wd.get("AlertCooldownMinutes") or 30) * 60

            if CLEAN_STOP.exists():
                # saída graciosa (Ctrl+C / notify_down) — missão cumprida
                print("watchdog: clean stop — saindo")
                break

            age = heartbeat_age_s()
            if age is not None and age <= stale_s:
                saw_alive = True
            elif saw_alive and (age is None or age > stale_s):
                now = time.time()
                if now - last_alert >= alert_cd:
                    if age is None:
                        msg = "bot morto · heartbeat sumiu — processo caiu?"
                    else:
                        mins = int(age // 60)
                        msg = (
                            f"bot morto · sem heartbeat há {mins}m "
                            f"(limite {int(stale_s // 60)}m) — reinicie main.py"
                        )
                    if tg.notify(msg, key="watchdog_dead", cooldown_s=0):
                        last_alert = now
                        print(f"[warn] {msg}")
            time.sleep(check_s)
    except KeyboardInterrupt:
        print("watchdog stop")
    finally:
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                PID_FILE.unlink(missing_ok=True)  # type: ignore[call-arg]
        except OSError:
            pass
        _release_lock(lock_fd)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--self-check", "-c"):
        assert _pid_alive(os.getpid())
        print("bot_watchdog ok")
    else:
        main()
