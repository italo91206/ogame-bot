"""E02 Defender T01+T02+T05+T04+T09: poll hostis, filtros, whitelist, autofleet, alarm."""
from __future__ import annotations

import threading
import time
from typing import Any

from features.fleetsave import attack_min_duration, fleetsave_celestial, process_recalls
from game import (
    current_resources,
    parse_celestials,
    parse_ogame_int,
    parse_ships,
    switch_celestial,
)
from game.attacks import (
    HostileAttack,
    attack_alert_lit,
    fleet_points,
    is_only_probes,
    list_hostile_attacks,
)
from game.models import Celestial, Coords
from runtime import Worker

_DEFAULTS = {
    "Active": True,
    "CheckIntervalMin": 1,
    "CheckIntervalMax": 22,
    "IgnoreProbes": True,
    "IgnoreWeakAttack": False,
    "WeakAttackRatio": 3,
    "IgnoreAttackIfIHave": {
        "Active": False,
        "MinResourcesToSave": 2_000_000,
        "MinFleetToSave": 20_000_000,
    },
    "WhiteList": [],
    "Autofleet": {"Active": False, "BuildCargosIfNeeded": True},
    "Alarm": {"Active": True},
    # CooldownMinutes = silêncio Telegram por id de frota (não a cada poll)
    "TelegramMessenger": {"Active": True, "CooldownMinutes": 60},
}

_MISSION_LABEL = {
    1: "ataque",
    2: "ACS",
    6: "spy",
    9: "destroy",
    10: "IPM",
}


def _cfg(cfg: dict, key: str) -> Any:
    if key in cfg and cfg[key] is not None:
        return cfg[key]
    return _DEFAULTS[key]


def play_alarm() -> None:
    """3 beeps (TBot ConsoleHelpers.PlayAlarm) — thread p/ não travar o tick."""

    def _run() -> None:
        try:
            import winsound

            for _ in range(3):
                winsound.Beep(1000, 350)
                time.sleep(0.7)
        except Exception:
            for _ in range(3):
                print("\a", end="", flush=True)
                time.sleep(0.7)

    threading.Thread(target=_run, name="defender-alarm", daemon=True).start()


def find_celestial(celestials: list[Celestial], dest: Coords) -> Celestial | None:
    for c in celestials:
        if (
            c.coords.galaxy == dest.galaxy
            and c.coords.system == dest.system
            and c.coords.position == dest.position
            and c.coords.type == dest.type
        ):
            return c
    return None


def skip_reason(
    attack: HostileAttack,
    *,
    whitelist: set[int],
    ignore_probes: bool,
    ignore_weak: bool,
    weak_ratio: int,
    ignore_have: dict,
    our_ships: dict[int, int] | None,
    our_resources: int | None,
) -> str | None:
    """TBot HandleAttack filters. None = react."""
    if attack.attacker_id and attack.attacker_id in whitelist:
        return f"whitelist {attack.attacker_name}"
    # IPM: T03 decides ABM; still count as threat for T01
    if attack.mission == 10:
        return None
    if attack.ships is not None:
        if ignore_probes and is_only_probes(attack.ships):
            return "só probes"
        if ignore_weak and our_ships is not None and weak_ratio > 0:
            ours = fleet_points(our_ships)
            theirs = fleet_points(attack.ships)
            if ours > 0 and theirs < ours / weak_ratio:
                return "ataque fraco"
    if ignore_have.get("Active") and our_ships is not None and our_resources is not None:
        min_res = int(ignore_have.get("MinResourcesToSave") or 0)
        min_fleet = int(ignore_have.get("MinFleetToSave") or 0)
        if our_resources < min_res and fleet_points(our_ships) * 1000 < min_fleet:
            return "baixo valor"
    return None


class DefenderWorker(Worker):
    def tick(self, ctx: dict[str, Any]) -> str:
        cfg = (ctx.get("settings") or {}).get("Defender") or {}
        tui = ctx.get("tui")
        page = ctx.get("page")
        if not _cfg(cfg, "Active"):
            self.reason = "off"
            return self.reason
        if page is None:
            self.reason = "sem page"
            return self.reason

        lo = max(1.0, float(_cfg(cfg, "CheckIntervalMin")))
        hi = max(lo, float(_cfg(cfg, "CheckIntervalMax")))
        self.interval_min = lo
        self.interval_max = hi
        saved_ids: set[int] = getattr(self, "_saved", None) or set()
        self._saved = saved_ids
        alerted: set[int] = getattr(self, "_alerted", None) or set()
        self._alerted = alerted
        was_threat = bool(getattr(self, "_was_threat", False))

        def _clear_banner() -> None:
            if tui and hasattr(tui, "set_under_attack"):
                tui.set_under_attack("")

        recalls = ctx.setdefault("fleet_recalls", [])
        try:
            process_recalls(page, recalls, tui)
        except Exception as e:
            if tui:
                tui.log(f"Defender: recall fail: {e}", "warn")

        try:
            attacks = list_hostile_attacks(page)
        except Exception as e:
            self.reason = f"eventList fail: {e}"
            if tui:
                tui.log(f"Defender: {self.reason}", "warn")
            self._next_wait = min(30.0, hi)
            return self.reason

        live_ids = {a.id for a in attacks}
        self._saved &= live_ids
        alerted &= live_ids

        if not attacks:
            # AJAX/DOM sem rows mas ícone Ataque! aceso → não mentir "safe"
            if attack_alert_lit(page):
                alarm_cfg = _cfg(cfg, "Alarm") or {}
                if not isinstance(alarm_cfg, dict):
                    alarm_cfg = {}
                detail = "alert UI (sem frota no eventList)"
                if tui and hasattr(tui, "set_under_attack"):
                    tui.set_under_attack(detail, count=1)
                if bool(alarm_cfg.get("Active", True)) and not was_threat:
                    play_alarm()
                if not was_threat:
                    msg = f"Defender: SOB ATAQUE · {detail}"
                    if tui:
                        tui.log(msg, "warn")
                    tg_cfg = _cfg(cfg, "TelegramMessenger") or {}
                    if not isinstance(tg_cfg, dict):
                        tg_cfg = {}
                    if bool(tg_cfg.get("Active", True)):
                        notify = ctx.get("notify")
                        if notify:
                            cd = max(60.0, float(tg_cfg.get("CooldownMinutes") or 60) * 60)
                            notify(msg, key="atk:alert", cooldown_s=cd)
                self._was_threat = True
                self.reason = "AMEAÇA alert"
                return self.reason
            self.reason = "safe"
            self._was_threat = False
            _clear_banner()
            return self.reason

        whitelist = {int(x) for x in (_cfg(cfg, "WhiteList") or []) if int(x)}
        ignore_probes = bool(_cfg(cfg, "IgnoreProbes"))
        ignore_weak = bool(_cfg(cfg, "IgnoreWeakAttack"))
        weak_ratio = max(1, int(_cfg(cfg, "WeakAttackRatio") or 3))
        ignore_have = _cfg(cfg, "IgnoreAttackIfIHave") or {}
        if not isinstance(ignore_have, dict):
            ignore_have = {}
        af = _cfg(cfg, "Autofleet") or {}
        if not isinstance(af, dict):
            af = {}
        autofleet = bool(af.get("Active"))
        build_cargos = bool(af.get("BuildCargosIfNeeded", True))
        alarm_cfg = _cfg(cfg, "Alarm") or {}
        if not isinstance(alarm_cfg, dict):
            alarm_cfg = {}
        alarm_on = bool(alarm_cfg.get("Active", True))
        tg_cfg = _cfg(cfg, "TelegramMessenger") or {}
        if not isinstance(tg_cfg, dict):
            tg_cfg = {}
        tg_on = bool(tg_cfg.get("Active", True))
        tg_cd_s = max(60.0, float(tg_cfg.get("CooldownMinutes") or 60) * 60.0)

        need_local = ignore_weak or bool(ignore_have.get("Active")) or autofleet
        celestials = parse_celestials(page) if need_local else []
        cache: dict[str, tuple[dict[int, int], int]] = {}

        threats = 0
        skipped = 0
        saved = 0
        banner_bits: list[str] = []
        for atk in attacks:
            our_ships = None
            our_res = None
            if need_local:
                key = f"{atk.dest.galaxy}:{atk.dest.system}:{atk.dest.position}:{atk.dest.type}"
                if key not in cache:
                    cel = find_celestial(celestials, atk.dest)
                    if cel is not None:
                        try:
                            switch_celestial(page, cel)
                            ships_raw = parse_ships(page)
                            ships = {sid: int(v.get("number") or 0) for sid, v in ships_raw.items()}
                            res = current_resources(page)
                            total = (
                                parse_ogame_int(res.get("metal", "0"))
                                + parse_ogame_int(res.get("crystal", "0"))
                                + parse_ogame_int(res.get("deut", "0"))
                            )
                            cache[key] = (ships, total)
                        except Exception:
                            cache[key] = ({}, 0)
                if key in cache:
                    our_ships, our_res = cache[key]

            why = skip_reason(
                atk,
                whitelist=whitelist,
                ignore_probes=ignore_probes,
                ignore_weak=ignore_weak,
                weak_ratio=weak_ratio,
                ignore_have=ignore_have,
                our_ships=our_ships,
                our_resources=our_res,
            )
            label = _MISSION_LABEL.get(atk.mission, str(atk.mission))
            eta = f"{atk.arrive_in:.0f}s"
            if why:
                skipped += 1
                if tui:
                    tui.log(
                        f"Defender: skip {label} {atk.dest} · {why}",
                        "info",
                    )
                continue
            threats += 1
            msg = (
                f"Defender: {label} de {atk.attacker_name} "
                f"({atk.attacker_id}) → {atk.dest} em {eta}"
            )
            banner_bits.append(f"{label} {atk.attacker_name}→{atk.dest} {eta}")
            is_new = atk.id not in alerted
            if is_new:
                alerted.add(atk.id)
                if tui:
                    tui.log(msg, "warn")
                if tg_on:
                    notify = ctx.get("notify")
                    if notify:
                        notify(msg, key=f"atk:{atk.id}", cooldown_s=tg_cd_s)

            if not autofleet or atk.id in self._saved or atk.mission == 10:
                continue
            cel = find_celestial(celestials, atk.dest)
            if cel is None:
                if tui:
                    tui.log(f"Defender: autofleet sem celestial {atk.dest}", "warn")
                continue
            afs = ((ctx.get("settings") or {}).get("SleepMode") or {}).get(
                "AutoFleetSave"
            ) or {}
            if not isinstance(afs, dict):
                afs = {}
            try:
                status = fleetsave_celestial(
                    page,
                    cel,
                    celestials,
                    min_duration=attack_min_duration(atk.arrive_in),
                    build_cargos=build_cargos and atk.arrive_in >= 600,
                    default_mission=str(afs.get("DefaultMission") or "Deploy"),
                    deut_to_leave=int(afs.get("DeutToLeave") or 0),
                    recall=bool(afs.get("Recall")),
                    recalls=recalls,
                )
            except Exception as e:
                status = f"fail: {e}"
            if status.startswith("ok"):
                self._saved.add(atk.id)
                saved += 1
            if tui:
                tui.log(f"Defender: autofleet {status}", "ok" if status.startswith("ok") else "warn")

        if threats:
            detail = f"{threats} ameaça(s) · " + " · ".join(banner_bits[:3])
            if len(banner_bits) > 3:
                detail += f" · +{len(banner_bits) - 3}"
            if tui and hasattr(tui, "set_under_attack"):
                tui.set_under_attack(detail, count=threats)
            if alarm_on and not was_threat:
                play_alarm()
            self._was_threat = True
            self.reason = (
                f"AMEAÇA {threats}"
                + (f" · save {saved}" if saved else "")
                + (f" · skip {skipped}" if skipped else "")
            )
        else:
            self._was_threat = False
            _clear_banner()
            self.reason = f"safe · skip {skipped}"
        return self.reason


if __name__ == "__main__":
    from game.attacks import parse_hostile_attacks_html, parse_ships_tooltip

    tip = (
        '&lt;table class=&quot;fleetinfo&quot;&gt;'
        "&lt;tr&gt;&lt;td&gt;Espionage Probe:&lt;/td&gt;"
        '&lt;td class=&quot;value&quot;&gt;5&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;'
    )
    ships = parse_ships_tooltip(tip)
    assert ships == {210: 5}, ships
    assert is_only_probes(ships)
    assert fleet_points(ships) == 5

    tip2 = (
        '<table class="fleetinfo">'
        '<tr><td>Cargueiro Grande:</td><td class="value">10</td></tr>'
        '<tr><td>Caça Ligeiro:</td><td class="value">2</td></tr>'
        "</table>"
    )
    s2 = parse_ships_tooltip(tip2)
    assert s2 == {203: 10, 204: 2}, s2
    assert fleet_points(s2) == 10 * 12 + 2 * 4
    assert not is_only_probes(s2)

    sample = """
    <div id="eventListWrap"><table><tr class="eventFleet" id="eventRow-99"
    data-mission-type="1" data-return-flight="false" data-arrival-time="9999999999">
    <td class="countDown hostile">x</td>
    <td class="coordsOrigin"><a>[1:2:3]</a></td>
    <td class="originFleet"><figure class="planetIcon planet"></figure></td>
    <td class="icon_movement"><span title="&lt;table class=&quot;fleetinfo&quot;&gt;
    &lt;tr&gt;&lt;td&gt;Espionage Probe:&lt;/td&gt;&lt;td&gt;3&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;"></span></td>
    <td class="destFleet"><figure class="planetIcon planet"></figure></td>
    <td class="destCoords"><a>[4:5:6]</a></td>
    <td class="sendMail"><a class="sendMail" data-playerid="42" title="Bob"></a></td>
    </tr></table></div>
    """
    atks = parse_hostile_attacks_html(sample, now=1.0)
    assert len(atks) == 1, atks
    a = atks[0]
    assert a.attacker_id == 42 and a.attacker_name == "Bob"
    assert a.dest == Coords(4, 5, 6, "Planet")
    assert is_only_probes(a.ships)

    why = skip_reason(
        a,
        whitelist={42},
        ignore_probes=True,
        ignore_weak=False,
        weak_ratio=3,
        ignore_have={"Active": False},
        our_ships=None,
        our_resources=None,
    )
    assert why and "whitelist" in why
    why2 = skip_reason(
        a,
        whitelist=set(),
        ignore_probes=True,
        ignore_weak=False,
        weak_ratio=3,
        ignore_have={"Active": False},
        our_ships=None,
        our_resources=None,
    )
    assert why2 == "só probes"
    print("defender ok")
