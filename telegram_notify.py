"""Telegram alertas + comandos (stdlib). Token/chat_id no .env."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
# ponytail: persiste chat_id após 1º /start se .env ainda não tem; preferir TELEGRAM_CHAT_ID
_BIND = ROOT / ".telegram_chat_id"

CommandFn = Callable[[], str | None]
LogFn = Callable[[str, str], None]  # msg, level


def _load_bind() -> str:
    try:
        return _BIND.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _save_bind(chat_id: str) -> None:
    try:
        _BIND.write_text(chat_id.strip() + "\n", encoding="utf-8")
    except OSError:
        pass


class TelegramBot:
    def __init__(
        self,
        token: str,
        chat_id: str = "",
        *,
        active: bool = True,
        commands: dict[str, CommandFn] | None = None,
        autopping_hours: float = 0,
        log: LogFn | None = None,
    ) -> None:
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip() or _load_bind()
        self.active = bool(active and self.token)
        self.commands = commands or {}
        self.autopping_hours = float(autopping_hours or 0)
        self._log = log
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = 0
        self.started_at = time.time()
        self._last_ping = 0.0
        self._last_key: dict[str, float] = {}
        self._cooldown_s = 120.0

    def _emit(self, msg: str, level: str = "info") -> None:
        if self._log:
            try:
                self._log(msg, level)
            except Exception:
                pass

    def uptime(self) -> str:
        s = int(time.time() - self.started_at)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}h{m:02d}m{sec:02d}s"

    def notify(
        self,
        text: str,
        *,
        key: str | None = None,
        cooldown_s: float | None = None,
    ) -> bool:
        if not self.active or not self.chat_id:
            return False
        if key:
            cd = self._cooldown_s if cooldown_s is None else cooldown_s
            now = time.time()
            if now - self._last_key.get(key, 0) < cd:
                return False
            self._last_key[key] = now
        body = (text or "")[:4000]
        ok = self._post(
            "sendMessage",
            {"chat_id": self.chat_id, "text": body},
        )
        tag = f" key={key}" if key else ""
        preview = body.replace("\n", " · ")[:120]
        if ok:
            self._emit(f"telegram: notify{tag} {preview}")
        else:
            self._emit(f"telegram: notify fail{tag} {preview}", "warn")
        return ok

    def start(self) -> None:
        if not self.active or self._thread is not None:
            return
        self._last_ping = time.time()  # próximo autopping daqui a EveryHours
        self._thread = threading.Thread(
            target=self._loop, name="telegram", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _post(self, method: str, data: dict[str, Any]) -> bool:
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(
            self._url(method), data=body, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                raw = json.loads(resp.read().decode())
            return bool(raw.get("ok"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return False

    def _get_updates(self) -> list[dict]:
        q = urllib.parse.urlencode(
            {"timeout": 25, "offset": self._offset, "allowed_updates": '["message"]'}
        )
        req = urllib.request.Request(self._url(f"getUpdates?{q}"))
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                raw = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return []
        if not raw.get("ok"):
            return []
        return list(raw.get("result") or [])

    def _allowed(self, chat_id: str) -> bool:
        if not self.chat_id:
            return True  # bind pending
        return str(chat_id) == str(self.chat_id)

    def _handle_message(self, msg: dict) -> None:
        chat = msg.get("chat") or {}
        cid = str(chat.get("id") or "")
        if not cid or not self._allowed(cid):
            return
        text = (msg.get("text") or "").strip()
        if not text:
            return

        if not self.chat_id:
            self.chat_id = cid
            _save_bind(cid)
            self._emit(f"telegram: chat ligado ({cid})")
            self._post(
                "sendMessage",
                {
                    "chat_id": cid,
                    "text": (
                        f"ok — chat ligado ({cid}).\n"
                        f"Coloque no .env:\nTELEGRAM_CHAT_ID={cid}"
                    ),
                },
            )
            return

        cmd = text.split()[0].split("@", 1)[0].lower()
        if cmd == "/start":
            self._emit("telegram: cmd /start")
            self._post(
                "sendMessage",
                {
                    "chat_id": cid,
                    "text": "comandos: /ping /status /pause /resume",
                },
            )
            return
        fn = self.commands.get(cmd)
        if fn is None:
            self._emit(f"telegram: cmd ignorado {cmd}")
            return
        self._emit(f"telegram: cmd {cmd}")
        try:
            reply = fn()
        except Exception as e:
            reply = f"erro: {e}"
            self._emit(f"telegram: cmd {cmd} erro {e}", "warn")
        if reply:
            self._post("sendMessage", {"chat_id": cid, "text": reply[:4000]})

    def _loop(self) -> None:
        while not self._stop.is_set():
            if (
                self.autopping_hours > 0
                and self.chat_id
                and time.time() - self._last_ping >= self.autopping_hours * 3600
            ):
                self._last_ping = time.time()
                self.notify(f"pong · uptime {self.uptime()}", key="autopping", cooldown_s=0)
            for u in self._get_updates():
                uid = u.get("update_id")
                if isinstance(uid, int):
                    self._offset = uid + 1
                msg = u.get("message")
                if isinstance(msg, dict):
                    self._handle_message(msg)
            if self._stop.wait(0.5):
                break


def from_settings(
    settings: dict[str, Any],
    *,
    commands: dict[str, CommandFn] | None = None,
    log: LogFn | None = None,
) -> TelegramBot:
    import os

    tg = settings.get("TelegramMessenger") or {}
    ping = settings.get("TelegramAutoPing") or {}
    token = os.environ.get("TELEGRAM_TOKEN") or ""
    chat = os.environ.get("TELEGRAM_CHAT_ID") or ""
    active = bool(tg.get("Active", True)) if token else False
    hours = float(ping.get("EveryHours") or 0) if ping.get("Active") else 0
    return TelegramBot(
        token,
        chat,
        active=active,
        commands=commands,
        autopping_hours=hours,
        log=log,
    )


def parse_cmd(text: str) -> str:
    """Primeiro token /cmd (sem @bot)."""
    t = (text or "").strip().split()[0] if (text or "").strip() else ""
    return t.split("@", 1)[0].lower()


if __name__ == "__main__":
    assert parse_cmd("/ping") == "/ping"
    assert parse_cmd("/STATUS@OgameItaloBot") == "/status"
    assert parse_cmd("") == ""
    bot = TelegramBot("", active=True)
    assert bot.active is False
    assert bot.notify("x") is False
    print("telegram_notify ok")
