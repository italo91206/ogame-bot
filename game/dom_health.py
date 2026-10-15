"""DOM liveness: last good planetList parse + bot uptime."""
from __future__ import annotations

import time

# ponytail: fixed thresholds; General.DomStaleSeconds if tuners appear
STALE_AFTER_S = 180.0
# telegram crítico: stale longo / falso-positivo sem last_good
CRITICAL_STALE_S = 40 * 60.0

_started_at = time.time()
_last_good_at: float | None = None


def boot(now: float | None = None) -> None:
    global _started_at, _last_good_at
    _started_at = now if now is not None else time.time()
    _last_good_at = None


def mark_good(now: float | None = None) -> None:
    global _last_good_at
    _last_good_at = now if now is not None else time.time()


def uptime(now: float | None = None) -> float:
    return (now if now is not None else time.time()) - _started_at


def since_good(now: float | None = None) -> float | None:
    """Seconds since last non-empty planetList; None if never."""
    if _last_good_at is None:
        return None
    return (now if now is not None else time.time()) - _last_good_at


def is_stale(max_age: float = STALE_AFTER_S, now: float | None = None) -> bool:
    now = now if now is not None else time.time()
    if _last_good_at is None:
        return (now - _started_at) >= max_age
    return (now - _last_good_at) >= max_age


def is_critical_stale(now: float | None = None) -> bool:
    return is_stale(CRITICAL_STALE_S, now)


def _fmt_dur(secs: float) -> str:
    s = int(max(0, secs))
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    return f"{s // 60}m{s % 60:02d}s"


def status_line(now: float | None = None) -> str:
    now = now if now is not None else time.time()
    sg = since_good(now)
    if sg is None:
        dom = f"DOM nunca · {_fmt_dur(now - _started_at)}"
    elif sg >= STALE_AFTER_S:
        dom = f"DOM stale {_fmt_dur(sg)}"
    else:
        dom = f"DOM ok {_fmt_dur(sg)}"
    return f"up {_fmt_dur(uptime(now))} · {dom}"


if __name__ == "__main__":
    boot(0.0)
    assert uptime(10.0) == 10.0
    assert since_good(10.0) is None
    assert is_stale(5.0, 10.0)
    assert not is_stale(20.0, 10.0)
    mark_good(10.0)
    assert since_good(40.0) == 30.0
    assert not is_stale(180.0, 40.0)
    assert is_stale(20.0, 40.0)
    assert not is_critical_stale(40.0)
    mark_good(0.0)
    assert is_critical_stale(CRITICAL_STALE_S)
    assert "up" in status_line(40.0) and "DOM" in status_line(40.0)
    print("dom_health ok")
