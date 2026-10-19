"""Background console key capture (Windows msvcrt). Thread → deque; main owns actions."""
from __future__ import annotations

import collections
import threading

# shortcuts that should abort a worker burst
INTERRUPT = frozenset("blwr")

# msvcrt: \xe0/\x00 prefix + scan → nome estável (não passa por .lower())
_SPECIAL = {"H": "up", "P": "down", "K": "left", "M": "right"}


class KeyPump:
    def __init__(self) -> None:
        self._buf: collections.deque[str] = collections.deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def start(self) -> None:
        if self._t and self._t.is_alive():
            return
        self._stop.clear()
        self._t = threading.Thread(target=self._run, name="keypump", daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # ponytail: msvcrt only; add tty when Linux matters
        try:
            import msvcrt
        except ImportError:
            return
        while not self._stop.is_set():
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    code = msvcrt.getwch()
                    name = _SPECIAL.get(code)
                    if name:
                        with self._lock:
                            self._buf.append(name)
                    continue
                if ch:
                    with self._lock:
                        self._buf.append(ch.lower())
            else:
                self._stop.wait(0.05)

    def get(self) -> str | None:
        with self._lock:
            return self._buf.popleft() if self._buf else None

    def drain(self) -> None:
        with self._lock:
            self._buf.clear()

    def pending(self) -> bool:
        with self._lock:
            return bool(self._buf)

    def has_interrupt(self) -> bool:
        with self._lock:
            return any(c in INTERRUPT for c in self._buf)


if __name__ == "__main__":
    assert _SPECIAL["H"] == "up" and _SPECIAL["P"] == "down"
    k = KeyPump()
    assert k.get() is None
    assert not k.pending() and not k.has_interrupt()
    with k._lock:
        k._buf.append("x")
        k._buf.append("b")
        k._buf.append("up")
    assert k.pending() and k.has_interrupt()
    assert k.get() == "x"
    assert k.has_interrupt()
    k.drain()
    assert not k.pending()
    print("keys ok")
