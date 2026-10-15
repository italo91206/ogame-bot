"""Shared game types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Coords:
    galaxy: int
    system: int
    position: int
    type: str = "Planet"  # Planet | Moon

    def __str__(self) -> str:
        return f"[{self.galaxy}:{self.system}:{self.position}]{'' if self.type == 'Planet' else ' M'}"


@dataclass
class Celestial:
    id: str
    name: str
    coords: Coords

    @property
    def label(self) -> str:
        """Log/TUI tag: planet name (coords only as fallback)."""
        n = (self.name or "").strip()
        return n if n else str(self.coords)


@dataclass
class FleetSlots:
    free: int
    total: int
    exp_free: int = 0
    exp_total: int = 0


LogFn = Callable[[str, str], None]


def _noop(msg: str, level: str = "info") -> None:
    pass
