"""Lifeform AutoResearch pick puro (caps / level) — sem Page."""
from __future__ import annotations

from game import Celestial, Tech


def is_lf_tech(tid: int) -> bool:
    slot = tid % 100
    return 1 <= slot <= 18 and tid // 100 in (112, 122, 132, 142)


def tech_cap_key(tid: int) -> str:
    """Slot 1..18 → MaxTechs11..16 / 21..26 / 31..36."""
    slot = tid % 100
    if slot <= 6:
        return f"MaxTechs1{slot}"
    if slot <= 12:
        return f"MaxTechs2{slot - 6}"
    return f"MaxTechs3{slot - 12}"


def under_cap(tid: int, level: int, cfg: dict) -> bool:
    key = tech_cap_key(tid)
    default = int(cfg.get("MaxResearchLevel") or 0)
    return level < int(cfg.get(key, default) or 0)


def excluded(c: Celestial, exclude: list) -> bool:
    for e in exclude or []:
        if (
            int(e.get("Galaxy", -1)) == c.coords.galaxy
            and int(e.get("System", -1)) == c.coords.system
            and int(e.get("Position", -1)) == c.coords.position
            and (e.get("Type") or "Planet") == c.coords.type
        ):
            return True
    return False


def pick_next(
    techs: dict[int, Tech],
    cfg: dict,
    *,
    afford: bool = True,
) -> int | None:
    """Among LF techs level ≥1 under cap; prefer lowest level."""

    def ok(t: Tech) -> bool:
        if not is_lf_tech(t.id) or t.level < 1 or not under_cap(t.id, t.level, cfg):
            return False
        if afford:
            return t.status == "on"
        return t.status in ("on", "disabled")

    cands = [t for t in techs.values() if ok(t)]
    if not cands:
        return None
    # ponytail: level asc instead of peek-all cheaper swap; add when needed
    return min(cands, key=lambda t: (t.level, t.id)).id


if __name__ == "__main__":
    cfg = {"MaxResearchLevel": 6, "MaxTechs11": 8, "MaxTechs12": 4}
    techs = {
        11201: Tech(11201, 5, "on"),
        11202: Tech(11202, 2, "on"),
        11203: Tech(11203, 1, "disabled"),
        11207: Tech(11207, 0, "on"),
    }
    assert tech_cap_key(11201) == "MaxTechs11"
    assert tech_cap_key(11207) == "MaxTechs21"
    assert tech_cap_key(11218) == "MaxTechs36"
    assert pick_next(techs, cfg) == 11202
    assert not under_cap(11202, 4, cfg)  # MaxTechs12=4 → level 4 capped
    assert pick_next(
        {11201: Tech(11201, 5, "on"), 11203: Tech(11203, 1, "disabled")},
        cfg,
        afford=False,
    ) == 11203
    assert is_lf_tech(13205) and not is_lf_tech(11101)
    print("lifeform_autoresearch_pick ok")
