---
name: log-triage
description: >-
  Triage meu-bot-ogame daily logs under logs/YYYY-MM-DD.log: explain a line,
  same-tick worker context, fleet/leave semantics, map reasons to features/*
  code, separate correct-but-confusing from bugs. Use when the user pastes or
  @-mentions a log line, asks why a worker did/didn't act, "verifique se está
  correto", "o que está acontecendo", sem slot, fail checkTarget, DOM morto,
  or to summarize recent bot behavior from logs.
---

# Log triage — meu-bot-ogame

## Goal

Answer: **o que o bot decidiu, por quê, e se está certo.**  
Não despejar log; entregar veredito curto + evidência.

## Log format

```
YYYY-MM-DD HH:MM:SS [level] message
```

- Path: `logs/YYYY-MM-DD.log` (hoje = data local; retention ~7d via `filelog.py`)
- Levels: `ok` | `info` | `warn` | `error`
- Prefixos comuns: `expo:`, `automine:`, `colonize:`, `lfmine:`, `lfresearch:`, `autocargo:`, worker status `AutoColonize: … · next …`

## Workflow

1. **Âncora** — linha citada (ou última ocorrência do worker). Ler ±30–80 linhas no mesmo arquivo.
2. **Mesmo tick** — bloco `next …` / `ok Worker:` no mesmo segundo ± poucos s. Expo, Colonize, Brain e Defender no mesmo momento.
3. **Semântica de slots** (armadilha #1)
   - No log: `fleet=FREE/TOTAL` e `sem slot frota (FREE/TOTAL)` usam **livres**, não used/total da UI OGame.
   - `General.SlotsToLeaveFree` = reserva do **jogador** (todos os workers).
   - `Expeditions.SlotsToLeaveFree` = leave do Expo (**≥** General). Expo para com `free ≤ leave_expo`; Colonize/Brain usam General.
   - `slots_available` ⇒ `free > leave`. Com leave=1 e free=1 → bloqueio **correto**.
4. **Mapear reason → código** — string do log → `self.reason =` / `_log(` em `features/<worker>.py`. Confirmar a condição, não só o texto.
5. **Histórico do worker** — grep do nome no mesmo dia. Padrão “sem slot” com expo `fleet=5/14` no mesmo minuto → investigar parse/DOM; “sem slot (1/14)” com expo aguardando → disputa/leave.
6. **Coords / fleet fail** — `0:0:N`, `setup g/s ''`, `checkTarget #100` → bug de destino/dispatch (`game/galaxy.py`, `game/fleet_*.py`), não “sem slot”.
7. **Veredito** — um de:
   - **Correto** (config/leave/fila) — o que mudar se o usuário quiser outro comportamento
   - **Confuso** (mensagem enganosa) — fix de reason, não de lógica
   - **Bug** — arquivo + condição raiz
   - **Competição** (Expo vs Colonize/LF) — apontar leave / Focus (`docs/FOCUS.md`)

## Output (obrigatório)

```
**Veredito:** correto | confuso | bug | competição

- O que: …
- Por quê: … (cite free/leave ou reason do código)
- Evidência: linha(s) + worker(s) no mesmo tick
- Próximo: … (1 ação ou “nada”)
```

Máx. ~8 linhas além do template. Sem tour de arquitetura.

## Não fazer

- Assumir que `(1/14)` na UI OGame = free do bot (UI costuma ser used/total).
- Subir `General.SlotsToLeaveFree` como “fix” de disputa entre workers (só reserva pro humano).
- Reescrever workers neste fluxo salvo se o usuário pedir fix.

## Glossário rápido

Ver [reasons.md](reasons.md).

## Settings a abrir se o tema for frota

- `settings.json` → `General.SlotsToLeaveFree`
- `Expeditions.SlotsToLeaveFree`
- `AutoColonize.SlotsToLeaveFree` = **planetas** a deixar livres (Astro), **não** frota
