# AGENTS.md — meu-bot-ogame

Guia para humanos e agentes. Fonte de verdade de features: [`FEATURES.md`](FEATURES.md). Paridade de comportamento: **TBot** (referência), implementação: **Playwright sync + Python**.

---

## Arquitetura

**Worker loop + adapter de UI** (inspirado no TBot, sem ogamed).

```
.env + settings.json
        │
        ▼
   config.py          credenciais / merge / hot-reload path
        │
        ▼
    main.py + compose.py   browser, sessão, TUI, wire workers
        │
        ├──────────────► tui.py / filelog.py
        │
        ▼
  runtime.py          agenda workers (intervalo random / _next_wait)
        │
        ▼
  features/           1 arquivo ≈ 1 épico (automine, expeditions, …)
                      subclass Worker; tick(ctx) → status curto
        │
        ▼
  game/               adapter Playwright: login, parse DOM, clicks,
                      celestials, filas, recursos
```

| Camada | Responsabilidade | Não faz |
|--------|------------------|---------|
| `main.py` / `compose.py` | wiring, login/sessão, tecla `b`, loop | lógica de mina/pesquisa |
| `runtime.py` | due/schedule/slots | DOM / pick de tech |
| `features/*` | decisão da feature + schedule inteligente | login / fingerprint |
| `game/` | I/O do jogo (Page → dados / ações) | política Brain (caps, prioridade) |
| `config.py` | settings | Playwright |
| `tui.py` | apresentação | regras de jogo |
| `docs/` | guias / rascunhos (FOCUS, Telegram, handoffs) | código |

**Fluxo de um tick**

1. `Runtime.run_once` chama `Worker.tick(ctx)` se due.
2. Worker lê `ctx["settings"]` / `ctx["page"]`, decide, age via `game.*`.
3. Worker seta `_next_wait` (countdown / ETA / retry) ou deixa `CheckInterval`.
4. TUI atualiza via `ctx["tui"]` / `ctx["refresh"]`.

**Config**

- Segredos: `.env` (`EMAIL`, `PASSWORD`, `UNIVERSE`, …).
- Features: `settings.json` → espelha chaves TBot (`Brain.AutoMine`, `Brain.AutoResearch`, …).
- Plano: `FEATURES.md` (`E##` / `E##-T##`, status `todo|doing|done|skip`).

---

## Modularização (como crescer)

1. **1 épico = 1 módulo em `features/`** (ex.: `features/automine.py`). Subpartes grandes → pacote `features/<nome>/`.
2. **Pick puro vs I/O**: funções de decisão (`pick_next`, caps, custos) sem `Page`; I/O em funções `*_once` / `*_celestial` que usam `game`.
3. **Reusar `game/`**: parse/click/switch/filas vivem no adapter. Worker não copia regex DOM.
4. **Self-check mínimo**: `python -m features.<mod>` com asserts no pick/helpers (sem framework).
5. **Parity lazy**: core TBot primeiro; DOIR/transports/etc. ficam `todo` no FEATURES até precisar.
6. **Sem abstração prematura**: não criar `IWorkerFactory` / DI até haver 2+ implementações reais.
7. **Registrar no `compose.py`**: worker + settings + linha TUI; stub some quando virar real.
8. **Atualizar `FEATURES.md`** no mesmo PR/commit da feature. Artefatos longos → `docs/`.

### Layout

```
meu-bot-ogame/
  main.py
  compose.py
  config.py
  runtime.py
  tui.py
  game/
  features/             # workers + helpers de feature
  docs/                 # FOCUS, Telegram, handoffs
  scripts/              # probes one-off
  FEATURES.md
  AGENTS.md
  settings.json
```

---

## Regra dura: 500 LOC

**Se um arquivo `.py` do projeto (exceto `.venv`) passar de 500 linhas, é obrigatório quebrá-lo antes de adicionar mais responsabilidade.**

- Contagem: linhas totais do arquivo (inclui branco/comentários) — `Measure-Object -Line` / `wc -l`.
- Ao tocar um arquivo **>500 LOC**: split faz parte da tarefa (não “depois”).
- Split preferido por **responsabilidade**, não por tamanho cego:
  - `game.py` → session / celestial / tech / queues / resources
  - feature gorda → `pick.py` + `worker.py` (ou pacote `features/<nome>/`)
- Novo código **não** entra no arquivo inchado: extrai o pedaço necessário e importa.
- Atualizar imports em `main` / workers no mesmo passo.
- Débito atual (baseline): `features/autoresearch.py` > 500 — priorizar no próximo toque. `game/` já split.

---

## Convenções de código

- Python 3.10+, sync Playwright.
- Estilo lean: stdlib primeiro; sem deps novas sem necessidade.
- Logs via TUI (`tui.log`); mensagens curtas em PT.
- Comentário `ponytail:` só para atalho deliberado + gatilho de upgrade.
- Não commitar `.env`, `session_*.json`, nem secrets.

---

## Checklist ao implementar um épico

1. Ler task em `FEATURES.md` + equivalente no TBot.
2. Reusar helpers em `game` / patterns de `automine` / `autoresearch`.
3. Worker + bloco em `settings.json` + wire em `main.py`.
4. Self-check do pick/helpers.
5. Marcar status no FEATURES.
6. Se algum `.py` tocado/criado >500 LOC → split antes de encerrar.
