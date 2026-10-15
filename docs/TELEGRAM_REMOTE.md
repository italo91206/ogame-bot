# Telegram — guia de implementação

Arquitetura alvo: **Telegram** avisa e comanda; interação humana (login/captcha) no **desktop local**. Paridade: TBot `TelegramMessenger` / épico **E16-T02**.

```
[celular]
   │  Telegram (alertas + /comandos)
   ▼
[PC: meu-bot-ogame] ── workers / sessão Playwright
   ▲
   │  humano no desktop (só quando login falhar)
[você]
```

---

## Parte A — Implementar o bot Telegram

### Pré-requisitos (manual, antes do código)

1. No Telegram, abra [@BotFather](https://t.me/BotFather).
2. `/newbot` → escolha nome e username (deve terminar em `bot`).
3. Guarde o **token** (segredo; não commitar).
4. Abra o chat com o bot novo e envie `/start`.
5. Descubra o **chat_id**:
   - Abra no browser: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Em `result[].message.chat.id` está o número (ex.: `123456789`).
6. Coloque no `.env` (não versionar):

```env
TELEGRAM_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

7. Espelhe chaves em `settings.json` (estilo TBot), ex.:

```json
"TelegramMessenger": {
  "Active": true,
  "Logging": false
},
"TelegramAutoPing": {
  "Active": true,
  "EveryHours": 6
}
```

Token e chat_id ficam no `.env`; flags de feature no `settings.json`.

---

### Etapa 1 — MVP: só avisos (`notify`)

**Objetivo:** receber no celular eventos extraordinários. Sem comandos ainda.

| # | Tarefa | Onde |
|---|--------|------|
| 1.1 | Módulo `telegram_notify.py`: `notify(text)` via `urllib`/`httpx` → `sendMessage` | raiz do projeto |
| 1.2 | Ler `TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID` do env; se ausente/Active=false → no-op | `config.py` / settings |
| 1.3 | Whitelist implícita: só manda pro `CHAT_ID` configurado | — |
| 1.4 | Ganchos de alerta (mensagens curtas em PT) | `main.py` |

**Eventos a notificar (Telegram = crítico; recover automático só em `logs/`):**

- bot up / bot parando (Ctrl+C)
- sessão inválida no boot → janela p/ login no desktop
- login incompleto / recover falhou → **precisa humano**
- cookies/sessão mortos → full login (`aguardando login` / `captcha detectado`) → **precisa humano**
- DOM stale **>40m** (falso-positivo / stuck) → bot down
- (opcional já) ataque via Defender

Recover automático de DOM (abrir browser + relogin) **não** manda Telegram — só `tick`/logs.
Quando o recover cai em login completo / captcha, **manda** (key `login_captcha`, cooldown 5min).

**Critério de pronto:** stuck em inspect ou stale >40m gera Telegram; recover que volta sozinho não.

---

### Etapa 2 — Comandos (long polling)

**Objetivo:** interagir com o bot sem estar no PC.

| # | Tarefa | Notas |
|---|--------|-------|
| 2.1 | Thread/daemon: loop `getUpdates` com `timeout≈30` | PC de casa = long polling (sem porta pública) |
| 2.2 | Ignorar updates cujo `chat.id` ≠ `TELEGRAM_CHAT_ID` | segurança básica |
| 2.3 | Comandos MVP | ver tabela abaixo |
| 2.4 | Wire no `main.py`: start no boot, stop no Ctrl+C | não bloquear o runtime |
| 2.5 | Log local de notify/comandos (`telegram: …` → TUI + `logs/`) | observabilidade |

**Comandos MVP:**

| Comando | Efeito |
|---------|--------|
| `/ping` | responde `pong` + uptime |
| `/status` | sessão ok? headless? workers? recovering/inspecting? sob ataque? |
| `/pause` | pausa workers (igual fluxo de inspect) |
| `/resume` | retoma workers se sessão saudável |

**Depois (paridade TBot, sob demanda):** `/sleep`, toggle features, fleet helpers (E16-T05).

**Critério de pronto:** do celular, `/status` responde enquanto o bot roda no PC; linha `telegram: cmd /status` aparece em `logs/`.

---

### Etapa 3 — Heartbeat + polish

| # | Tarefa |
|---|--------|
| 3.1 | Auto-ping a cada `TelegramAutoPing.EveryHours` (uptime + “ainda vivo”) |
| 3.2 | Deduplicar spam (ex.: não reenviar “DOM morto” a cada tick; cooldown) |
| 3.3 | Mensagem de recover operacional: *“No desktop: complete o login na janela do Chrome, depois /resume ou tecla b”* |
| 3.4 | Atualizar `FEATURES.md` (E16-T02 → `doing`/`done`) + `.env.example` |
| 3.5 | Self-check mínimo no módulo (asserts de parse de comando / no-op sem token) |

---

### Etapa 4 — (Opcional) Endurecimento

- Reinício automático do processo (Task Scheduler Windows) se o Python cair
- Screenshot do browser no alerta de captcha (`sendPhoto`)
- Comando `/session_ok` depois do login (alternativa à tecla `b`)
- Logs do jogo no Telegram só se `Logging: true` (cuidado com flood) — distinto do log local `telegram: …`

---

### Layout de código sugerido

```
meu-bot-ogame/
  telegram_notify.py   # notify + poll de comandos (1 arquivo até ~200 LOC)
  main.py              # wire: notify nos ganchos; start/stop poller; log callback
  config.py            # env + settings merge
  settings.json        # Active / AutoPing
  .env                 # TOKEN + CHAT_ID
```

Regras do projeto: decisão/I-O separados; não misturar Telegram com pick de Brain; se passar de 500 LOC, split.

**Deps:** preferir stdlib (`urllib.request`) no MVP; só adicionar lib Telegram se o poller ficar complexo.

Referência TBot: `TBot/Services/TelegramMessenger.cs` (send + polling + auto-ping + comandos).

---

## Parte B — Runbook operacional

### Fluxo normal

1. PC ligado, `python main.py` (ou serviço) rodando headless.
2. Telegram manda auto-ping de vez em quando → você ignora.
3. Workers rodam sozinhos.

### Quando receber “login necessário” / “DOM morto”

1. No **desktop**, localize a janela do **Chrome/Chromium** do Playwright.
2. Complete login Gameforge / captcha / universo.
3. Confirme sessão:
   - tecla `b` no terminal do bot, **ou**
   - `/resume` no Telegram (quando a sessão já estiver ok).
4. Espere alerta “sessão ok / bot retomado”.

### Se o Telegram parar de responder

- PC dormiu, sem internet, ou processo Python morreu.
- Resolva no desktop; o bot só responde enquanto o processo estiver vivo.

---

## Checklist “PC pode ficar sozinho”

- [ ] PC na tomada; sleep/hibernação desligados (ou adiados)
- [ ] Bot sobe após login Windows (atalho Startup ou Task Scheduler)
- [ ] Telegram `/ping` responde
- [ ] Simulou recover: janela headed aparece no desktop e login completa
- [ ] `logs/` registra `telegram: notify` / `telegram: cmd …`

---

## Ordem de execução sugerida

| Ordem | O quê | Depende de |
|-------|--------|------------|
| 0 | BotFather + `.env` | — |
| 1 | Etapa 1 `notify` + ganchos de sessão | 0 |
| 2 | Etapa 2 comandos MVP + log local | 1 |
| 3 | Etapa 3 heartbeat + texto de recover | 2 |
| 4 | Etapa 4 só se doer | 3 |

Não implementar PWA nem proxy de cookies: login humano no desktop do PC, mantendo fingerprint/`session_*.json` locais.

---

## Critérios de aceite (feature completa MVP)

- [ ] Evento de sessão morta gera Telegram no celular
- [ ] `/ping` e `/status` funcionam com o processo no ar
- [ ] Auto-ping confirma que o processo está vivo
- [ ] No desktop dá para completar login e o bot retoma
- [ ] Interações Telegram aparecem em `logs/` (`telegram: …`)
- [ ] Token/chat_id não estão no git; `FEATURES.md` E16-T02 atualizado
