"""Resources parse, book, production."""
from __future__ import annotations

import html as htmlmod
import re
import time
from dataclasses import dataclass, field

from playwright.sync_api import Page

from .models import Celestial

def grab_resource(html: str, rid: str) -> str:
    m = re.search(rf'id="{rid}"[^>]*>\s*([^<]+)', html)
    return m.group(1).strip() if m else "?"


def current_resources(page: Page) -> dict[str, str]:
    html = page.content()
    return {
        "metal": grab_resource(html, "resources_metal"),
        "crystal": grab_resource(html, "resources_crystal"),
        "deut": grab_resource(html, "resources_deuterium"),
        "energy": grab_resource(html, "resources_energy"),
    }


def parse_ogame_int(raw: str) -> int:
    """Parse UI numbers like '1.234', '-500', '2M' → int."""
    s = (raw or "").strip().replace("\xa0", "").replace(" ", "")
    if not s or s == "?":
        return 0
    mult = 1
    if s[-1] in "Kk":
        mult, s = 1_000, s[:-1]
    elif s[-1] in "Mm":
        mult, s = 1_000_000, s[:-1]
    elif s[-1] in "Bb":
        mult, s = 1_000_000_000, s[:-1]
    s = s.replace(".", "").replace(",", "")
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def format_ogame_int(n: int) -> str:
    n = int(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{sign}{v:.1f}M".replace(".0M", "M")
    if n >= 10_000:
        v = n / 1_000
        return f"{sign}{v:.1f}k".replace(".0k", "k")
    return f"{sign}{n:,}".replace(",", ".")


def format_cost(cost: dict[str, int]) -> str:
    """Log-friendly M/C/D (ex.: M1M C335.2k D0)."""
    return (
        f"M{format_ogame_int(int(cost.get('metal', 0)))} "
        f"C{format_ogame_int(int(cost.get('crystal', 0)))} "
        f"D{format_ogame_int(int(cost.get('deut', 0)))}"
    )


@dataclass
class ResSnap:
    """DOM snapshot + prod/h; project until next overview."""

    metal: int
    crystal: int
    deut: int
    energy: int
    prod_metal: int = 0
    prod_crystal: int = 0
    prod_deut: int = 0
    at: float = 0.0

    def __post_init__(self) -> None:
        if not self.at:
            self.at = time.time()

    def projected(self, now: float | None = None) -> dict[str, int]:
        now = now if now is not None else time.time()
        h = max(0.0, (now - self.at) / 3600.0)
        # ponytail: no storage cap; add when DepositHours matters
        return {
            "metal": self.metal + int(self.prod_metal * h),
            "crystal": self.crystal + int(self.prod_crystal * h),
            "deut": self.deut + int(self.prod_deut * h),
            "energy": self.energy,
        }

    def spend(self, cost: dict[str, int]) -> None:
        cur = self.projected()
        self.metal = max(0, cur["metal"] - int(cost.get("metal", 0)))
        self.crystal = max(0, cur["crystal"] - int(cost.get("crystal", 0)))
        self.deut = max(0, cur["deut"] - int(cost.get("deut", 0)))
        self.energy = cur["energy"]
        self.at = time.time()


# ponytail: absolute vs projected; false positives rare (prod/h << drop)
JUMP_ABS = 50_000


@dataclass
class ResourceBook:
    """Per-celestial resource ticker between overview visits."""

    snaps: dict[str, ResSnap] = field(default_factory=dict)
    meta: dict[str, tuple[str, str, str]] = field(default_factory=dict)

    def put(
        self, c: Celestial, res: dict[str, str], prod: dict[str, int]
    ) -> bool:
        """Store snap. True if stock jumped past production projection (drop/incoming)."""
        metal = parse_ogame_int(res.get("metal", "0"))
        crystal = parse_ogame_int(res.get("crystal", "0"))
        deut = parse_ogame_int(res.get("deut", "0"))
        jumped = False
        old = self.snaps.get(c.id)
        if old:
            p = old.projected()
            jumped = (
                metal - p["metal"] >= JUMP_ABS
                or crystal - p["crystal"] >= JUMP_ABS
                or deut - p["deut"] >= JUMP_ABS
            )
        self.snaps[c.id] = ResSnap(
            metal=metal,
            crystal=crystal,
            deut=deut,
            energy=parse_ogame_int(res.get("energy", "0")),
            prod_metal=int(prod.get("metal", 0)),
            prod_crystal=int(prod.get("crystal", 0)),
            prod_deut=int(prod.get("deut", 0)),
        )
        self.meta[c.id] = (c.name, str(c.coords), c.coords.type)
        return jumped

    def spend(self, celestial_id: str, cost: dict[str, int]) -> None:
        snap = self.snaps.get(celestial_id)
        if snap:
            snap.spend(cost)

    def push_tui(self, tui) -> None:
        # keep TUI order stable; preserve last_action via upsert
        seen: set[str] = set()
        for cid, snap in self.snaps.items():
            name, coords, kind = self.meta[cid]
            seen.add(name)
            p = snap.projected()
            tui.upsert_planet(
                name,
                coords=coords,
                metal=format_ogame_int(p["metal"]),
                crystal=format_ogame_int(p["crystal"]),
                deut=format_ogame_int(p["deut"]),
                energy=format_ogame_int(p["energy"]),
                kind=kind,
            )
        if seen and getattr(tui, "planets", None) is not None:
            tui.planets[:] = [row for row in tui.planets if row.name in seen]


def _prod_from_tooltip_html(title: str) -> int:
    """Extract hourly production from a resourceTooltip HTML blob."""
    title = htmlmod.unescape(title or "")
    m = re.search(
        r"(?:Current production|Produ[çc][aã]o atual|Produzindo)"
        r"[^<]*</th>\s*<td>\s*<span[^>]*>\s*([+\-]?[\d.,\s]+)",
        title,
        re.I | re.S,
    )
    if m:
        return abs(parse_ogame_int(m.group(1)))
    spans = re.findall(r"<span[^>]*>\s*([+\-]?[\d.,\s]+)\s*</span>", title)
    # Available, Storage, Current production — same order as ogamed
    return abs(parse_ogame_int(spans[2])) if len(spans) >= 3 else 0


def _storage_from_tooltip_html(title: str) -> int:
    """Storage capacity from resourceTooltip (2nd span / Capacidade row)."""
    title = htmlmod.unescape(title or "")
    m = re.search(
        r"(?:Storage capacity|Capacidade)"
        r"[^<]*</th>\s*<td>\s*<span[^>]*>\s*([\d.,\s]+)",
        title,
        re.I | re.S,
    )
    if m:
        return abs(parse_ogame_int(m.group(1)))
    spans = re.findall(r"<span[^>]*>\s*([+\-]?[\d.,\s]+)\s*</span>", title)
    return abs(parse_ogame_int(spans[1])) if len(spans) >= 2 else 0


def _fetch_resources_blocks(page: Page) -> dict[str, dict]:
    """Raw metal/crystal/deuterium blocks from fetchResources ajax."""
    try:
        base = page.url.split("?")[0]
        cp = re.search(r"[?&]cp=(\d+)", page.url)
        url = f"{base}?page=fetchResources&ajax=1"
        if cp:
            url += f"&cp={cp.group(1)}"
        resp = page.context.request.get(url)
        if not resp.ok:
            return {}
        data = (resp.json() or {}).get("resources") or {}
        return {k: (data.get(k) or {}) for k in ("metal", "crystal", "deuterium")}
    except Exception:
        return {}


def _prod_via_fetch(page: Page) -> dict[str, int]:
    """fetchResources ajax — production already applies energy factor (%)."""
    out = {"metal": 0, "crystal": 0, "deut": 0}
    blocks = _fetch_resources_blocks(page)
    if not blocks:
        return out
    for key, api in (("metal", "metal"), ("crystal", "crystal"), ("deut", "deuterium")):
        block = blocks.get(api) or {}
        # v9+: production per second; older: only tooltip with +N/h
        raw = block.get("production")
        if isinstance(raw, (int, float)):
            out[key] = int(round(float(raw) * 3600))
        else:
            out[key] = _prod_from_tooltip_html(block.get("tooltip") or "")
    return out


def _storage_via_fetch(page: Page) -> dict[str, int]:
    out = {"metal": 0, "crystal": 0, "deut": 0}
    blocks = _fetch_resources_blocks(page)
    if not blocks:
        return out
    for key, api in (("metal", "metal"), ("crystal", "crystal"), ("deut", "deuterium")):
        block = blocks.get(api) or {}
        raw = block.get("storage")
        if isinstance(raw, (int, float)):
            out[key] = int(raw)
        else:
            out[key] = _storage_from_tooltip_html(block.get("tooltip") or "")
    return out


def _box_tooltips(page: Page) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, rid in (
        ("metal", "metal_box"),
        ("crystal", "crystal_box"),
        ("deut", "deuterium_box"),
    ):
        loc = page.locator(f"#{rid}")
        out[key] = loc.get_attribute("title") or "" if loc.count() else ""
    return out


def _prod_via_dom_tooltips(page: Page) -> dict[str, int]:
    return {k: _prod_from_tooltip_html(t) for k, t in _box_tooltips(page).items()}


def _storage_via_dom_tooltips(page: Page) -> dict[str, int]:
    return {k: _storage_from_tooltip_html(t) for k, t in _box_tooltips(page).items()}


def resource_production_per_hour(page: Page) -> dict[str, int]:
    """Hourly metal/crystal/deut (energy factor included). Prefer ajax over DOM."""
    prod = _prod_via_fetch(page)
    if any(prod.values()):
        return prod
    return _prod_via_dom_tooltips(page)


def resource_storage(page: Page) -> dict[str, int]:
    """Metal/crystal/deut storage capacity. Prefer ajax over DOM."""
    stor = _storage_via_fetch(page)
    if any(stor.values()):
        return stor
    return _storage_via_dom_tooltips(page)


def peek_tech_costs(page: Page, tech_id: int) -> dict[str, int] | None:
    """Open tech detail; read upgrade costs. Does not click Upgrade."""
    li = page.locator(f'li.technology[data-technology="{tech_id}"]')
    if not li.count():
        return None
    li.first.click()
    try:
        page.locator("div.costs").first.wait_for(state="visible", timeout=5_000)
    except Exception:
        return None
    costs: dict[str, int] = {}
    for key, cls in (("metal", "metal"), ("crystal", "crystal"), ("deut", "deuterium")):
        el = page.locator(f"div.costs li.{cls}")
        costs[key] = (
            parse_ogame_int(el.first.get_attribute("data-value") or "0") if el.count() else 0
        )
    return costs


def secs_until_resources(
    cost: dict[str, int], have: dict[str, int], prod_per_hour: dict[str, int]
) -> float | None:
    """Seconds until have >= cost from planet production. None if impossible."""
    worst = 0.0
    for k in ("metal", "crystal", "deut"):
        missing = int(cost.get(k, 0)) - int(have.get(k, 0))
        if missing <= 0:
            continue
        ph = int(prod_per_hour.get(k, 0))
        if ph <= 0:
            return None
        worst = max(worst, missing / (ph / 3600.0))
    return worst


if __name__ == "__main__":
    tip_en = (
        'Metal|<table class="resourceTooltip">'
        "<tr><th>Available:</th><td><span>1,000</span></td></tr>"
        "<tr><th>Storage capacity</th><td><span>5,000</span></td></tr>"
        '<tr><th>Current production:</th><td><span class="undermark">+13,642</span></td></tr>'
        "</table>"
    )
    tip_pt = (
        "Metal|<table>"
        "<tr><th>Disponível:</th><td><span>1.000</span></td></tr>"
        "<tr><th>Capacidade</th><td><span>5.000</span></td></tr>"
        "<tr><th>Produção atual:</th><td><span>+2.500</span></td></tr>"
        "</table>"
    )
    assert _prod_from_tooltip_html(tip_en) == 13_642
    assert _prod_from_tooltip_html(tip_pt) == 2_500
    assert _storage_from_tooltip_html(tip_en) == 5_000
    assert _storage_from_tooltip_html(tip_pt) == 5_000
    assert (
        secs_until_resources(
            {"metal": 1000, "crystal": 0, "deut": 0},
            {"metal": 0, "crystal": 0, "deut": 0},
            {"metal": 3600, "crystal": 0, "deut": 0},
        )
        == 1000
    )
    from types import SimpleNamespace

    book = ResourceBook()
    c = SimpleNamespace(id="1", name="Home", coords=SimpleNamespace(type="Planet"))
    assert book.put(c, {"metal": "1000", "crystal": "0", "deut": "0", "energy": "0"}, {}) is False
    assert book.put(c, {"metal": "2000", "crystal": "0", "deut": "0", "energy": "0"}, {}) is False
    assert book.put(
        c,
        {"metal": str(2000 + JUMP_ABS), "crystal": "0", "deut": "0", "energy": "0"},
        {},
    ) is True
    print("resources ok")
