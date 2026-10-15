# Reasons / mensagens frequentes

Mapa curto log → significado. Código canônico em `features/`.

## Frota / expo / colonize

| Log | Significado |
|-----|-------------|
| `expo: pacing fleet=F/T expo=E/X` | F livres de T frota; E livres de X expo. Sem envio neste tick. |
| `Expeditions: aguardando slot` | `exps_to_send` = 0 (leave, WaitForAll/Majority, ou sem room). |
| `AutoColonize: sem slot frota (F/T)` | `free > leave_general` falso. Leave Expo **não** aparece aqui. |
| `slots DOM 0/0` | `#slots` não parseou — página errada / DOM morto, não “frota cheia”. |
| `CS em voo (N)` | Já há N colonize outbound ≥ need. |
| `slots ok P/CAP` | Planetas sob cap Astro (não frota). |
| `coords inválidas` / `→ 0:0:N` | Destino galaxy/system zerado — bug scan/send. |
| `fail checkTarget … #100` | AJAX V13; fallback UI; se dest `0:0` o #100 é sintoma. |
| `transport: sem slot` | Brain/mina quer transport; frota sob leave. |

## Brain / filas

| Log | Significado |
|-----|-------------|
| `fila ocupada` / `pesquisa em andamento` | Aguarda countdown; `_next_wait` ≈ ETA. |
| `sem recurso p/ …` + `sem ETA` | Prod insuficiente ou falta res; transport pode falhar por slot. |
| `Reach:` / `Not reach:` | Celestial atual vs outros no sweep. |
| `todos excluded` | Nenhum planeta elegível no tick. |

## Sessão / DOM

| Log | Significado |
|-----|-------------|
| `DOM morto` | Health check falhou → re-login / headed. |
| `browser visível — workers pausados` | Tecla `b` / janela; workers param até headless. |
| `reconfirm — tick em todos` | Tecla `r` ou retomada — todos due de uma vez (ordem = `compose.py`). |
| `sessão reaproveitada` | storage state OK. |

## Leave cheat-sheet

```
General.SlotsToLeaveFree = G          # floor jogador
Expeditions.SlotsToLeaveFree = E      # Expo usa max(G, E)
Colonize/Discovery/Farm/transports    # usam G (Farm pode ter próprio)
AutoColonize.SlotsToLeaveFree         # planetas livres no cap, NÃO frota
```

Expo enche até `free <= max(G,E)`. Colonize precisa `free > G`.
