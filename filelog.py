"""Daily log files under logs/; drop files older than KEEP_DAYS."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
KEEP_DAYS = 7
_cleaned_on: date | None = None


def _today_path() -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    return LOG_DIR / f"{date.today().isoformat()}.log"


def cleanup(keep_days: int = KEEP_DAYS) -> None:
    if not LOG_DIR.exists():
        return
    cutoff = date.today() - timedelta(days=keep_days)
    for p in LOG_DIR.glob("????-??-??.log"):
        try:
            if date.fromisoformat(p.stem) < cutoff:
                p.unlink(missing_ok=True)
        except ValueError:
            continue


def write(msg: str, level: str = "info") -> None:
    global _cleaned_on
    today = date.today()
    if _cleaned_on != today:
        cleanup()
        _cleaned_on = today
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {msg}\n"
    with _today_path().open("a", encoding="utf-8") as f:
        f.write(line)


def tail(n: int = 50) -> list[str]:
    """Last n lines of today's log (newest last)."""
    from collections import deque

    path = _today_path()
    if not path.exists() or n <= 0:
        return []
    with path.open(encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in deque(f, maxlen=n)]


if __name__ == "__main__":
    write("self-check", "ok")
    assert _today_path().exists()
    cleanup(keep_days=0)  # would delete today if stem < today — keep_days=0 means cutoff=today, so only older
    # recreate after aggressive test
    write("still ok", "ok")
    assert any("still ok" in ln for ln in tail(5))
    print("filelog ok", _today_path())
