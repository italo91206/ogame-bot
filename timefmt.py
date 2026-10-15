"""Human duration masks for logs/TUI (omit zero units)."""
from __future__ import annotations

import re

_SEC_RE = re.compile(r"\b(\d+(?:\.\d+)?)s\b")


def fmt_duration(secs: float | int) -> str:
    """6367 → '1h 46m 7s'; 5*3600 → '5h'; 45 → '45s' (no leading 0d/0h)."""
    s = int(round(float(secs)))
    if s < 0:
        s = 0
    if s == 0:
        return "0s"
    d, rem = divmod(s, 86_400)
    h, rem = divmod(rem, 3_600)
    m, sec = divmod(rem, 60)
    parts: list[str] = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if sec or not parts:
        parts.append(f"{sec}s")
    return " ".join(parts)


def mask_seconds_in_text(text: str) -> str:
    """Replace bare '1234s' tokens with fmt_duration."""
    return _SEC_RE.sub(lambda m: fmt_duration(float(m.group(1))), text)


if __name__ == "__main__":
    assert fmt_duration(0) == "0s"
    assert fmt_duration(45) == "45s"
    assert fmt_duration(90) == "1m 30s"
    assert fmt_duration(3600) == "1h"
    assert fmt_duration(5 * 3600) == "5h"
    assert fmt_duration(6367) == "1h 46m 7s"
    assert fmt_duration(86_400 + 90) == "1d 1m 30s"
    assert mask_seconds_in_text("next 6367s") == "next 1h 46m 7s"
    assert mask_seconds_in_text("ETA 90s → cap 120s") == "ETA 1m 30s → cap 2m"
    assert "8000ms" in mask_seconds_in_text("Timeout 8000ms")
    print("timefmt ok")
