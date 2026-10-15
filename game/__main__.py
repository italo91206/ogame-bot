"""python -m game — self-check (ex-game.py __main__)."""
from __future__ import annotations

import re
import time

from .lobby import (
    _assert_universe,
    _find_account,
    _ingame,
    _lobby_base,
    _lobby_locale,
    _lobby_token,
    _resolve_server,
    _server_host,
)
from .celestial import _COORDS_RE
from .models import Coords
from .queues import parse_building_queue
from .resources import (
    ResSnap,
    format_cost,
    format_ogame_int,
    parse_ogame_int,
    secs_until_resources,
)
from .browser import session_path

c = Coords(1, 2, 3, "Moon")
assert str(c) == "[1:2:3] M"
assert _COORDS_RE.search("[4:55:6]").groups() == ("4", "55", "6")
assert parse_ogame_int("1.234") == 1234
assert parse_ogame_int("-500") == -500
assert parse_ogame_int("2M") == 2_000_000
assert session_path({"Name": "My Device"}).name == "session_My_Device.json"


class _P:
    def __init__(self, url: str):
        self.url = url


assert _ingame(_P("https://x/game/index.php?page=ingame&component=overview"))
assert _ingame(_P("https://s182-br.ogame.gameforge.com/game/index.php"))
assert not _ingame(_P("https://lobby.ogame.gameforge.com/en_GB/accounts"))
assert re.fullmatch(r"s\d+[-\w]*\.ogame\.gameforge\.com", "s182-br.ogame.gameforge.com")
assert not re.fullmatch(r"s\d+[-\w]*\.ogame\.gameforge\.com", "lobby.ogame.gameforge.com")


class _Ctx:
    def cookies(self):
        return [{"name": "gf-token-production", "value": "tok"}]


assert _lobby_token(_Ctx()) == "tok"
servers = [
    {"name": "Dione", "language": "br", "number": 182, "accountGroup": "br_182"},
    {"name": "Dione", "language": "hu", "number": 182, "accountGroup": "hu_182"},
    {"name": "Kalyke", "language": "br", "number": 183, "accountGroup": "br_183"},
]
assert _resolve_server(servers, "Dione", "br")["accountGroup"] == "br_182"
assert (
    _find_account(
        [{"id": 1, "server": {"language": "br", "number": 183}}],
        _resolve_server(servers, "Dione", "br"),
    )
    is None
)
assert (
    _find_account(
        [{"id": 9, "server": {"language": "br", "number": 182}}],
        _resolve_server(servers, "Dione", "br"),
    )["id"]
    == 9
)
assert _server_host(servers[0]) == "s182-br.ogame.gameforge.com"
assert _lobby_locale("br") == "pt_BR"
assert _lobby_base("lobby", "br").endswith("/pt_BR")


class _G:
    def __init__(self, url: str):
        self.url = url


try:
    _assert_universe(_G("https://s183-br.ogame.gameforge.com/game/index.php"), servers[0], "Dione")
    raise AssertionError("expected mismatch")
except RuntimeError as e:
    assert "universo errado" in str(e)
_assert_universe(
    _G("https://s182-br.ogame.gameforge.com/game/index.php?page=ingame"),
    servers[0],
    "Dione",
)
assert (
    secs_until_resources(
        {"metal": 3600, "crystal": 0, "deut": 0},
        {"metal": 0, "crystal": 0, "deut": 0},
        {"metal": 3600, "crystal": 1, "deut": 1},
    )
    == 3600
)
assert format_ogame_int(1_234) == "1.234"
assert format_ogame_int(12_000) == "12k"
assert format_ogame_int(40_000) == "40k"
assert format_cost({"metal": 1_005_747, "crystal": 335_249, "deut": 0}) == (
    "M1M C335.2k D0"
)
snap = ResSnap(1000, 500, 0, 100, prod_metal=3600, at=time.time() - 1)
assert snap.projected()["metal"] >= 1001
snap.spend({"metal": 500})
assert snap.metal >= 500
assert parse_building_queue('<div class="construction"></div>', 1000) == (0, 0)
assert parse_building_queue(
    'var restTimebuilding = 1100 - onclick="cancelbuilding(4, 1)"', 1000
) == (4, 100)
assert parse_building_queue(
    "new CountdownTimer('buildingCountdown', 42,); cancelbuilding(1, 0)",
    0,
) == (1, 42)
print("game ok")
