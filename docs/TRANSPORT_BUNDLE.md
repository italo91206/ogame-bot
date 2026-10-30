# TRANSPORT_BUNDLE.md — E04-T05

Transport Origin → dest soma custos das **filas paralelas idle** no mesmo voo (best-effort N∈{1..4}).

Feature: [`FEATURES.md`](../FEATURES.md) **E04-T05**.

---

## Slots

| Slot | Fila | Worker | Quando entra |
|------|------|--------|--------------|
| Clássico | recursos / instalações | AutoMine | feature + Transports on; fila idle (lua: só este slot) |
| Research | pesquisa clássica | AutoResearch | `Target` fixo = dest; lab/fila idle |
| LF prédio | edifícios lifeform | Lifeform AutoMine | crystal gate; não se robots/nanites na clássica; Prevent vs mina |
| LF tech | pesquisa lifeform | Lifeform AutoResearch | feature + Transports on; fila idle |

---

## Comportamento

- Best-effort: manda para quantos slots idle + pick + Transports.on der (1…4); próximo tick completa o que faltou.
- Um voo por dest enquanto `incoming` — bundle no primeiro send.
- Prioridade se Origin não cobre a soma: clássico > research > LF tech > LF build (1º slot pode ser parcial).
- Soma clampada ao storage do dest.
- Lookahead same-queue (clássico / LF prédio / LF tech) se `2×flight ≥ buildTime`.
- Flight SC/LC com combustão/impulso; tags no TUI unidas com `+`.

---

## Módulos

| Peça | Faz |
|------|-----|
| `features/transport_bundle.py` | `bundle_parallel_cost`, clamp, fit Origin, `send_bundled_transport`, log `detail` |
| `features/transport_bundle_peek.py` | peek dos siblings idle (+ razões de omit) |
| `features/transport_lookahead.py` | stack fila clássica + `cargo_speed` / flight |
| `features/transport_lookahead_lf.py` | stack LF prédio / LF tech |
| `features/transports.py` | `send_miner_transport` (fit/clamp no path `parts=`) |
| `features/automine_io.py` | wire AutoMine (build + sats) |
| `features/autoresearch.py` | wire AutoResearch |
| `features/lifeform_automine.py` / `_pick.py` | wire LF build + `mine_too_cheap` |
| `features/lifeform_autoresearch.py` / `_pick.py` | wire LF tech |
| `tui.log` / `tui.log_file` | (a) TUI compacto · (b) file-only decisão |
