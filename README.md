# meu-bot-ogame

Bot OGame (Playwright + Python): login Gameforge, workers no loop, TUI no terminal e alertas/comandos via Telegram.

Paridade de comportamento: **TBot**. Plano detalhado: [`FEATURES.md`](FEATURES.md). Arquitetura: [`AGENTS.md`](AGENTS.md).

---

## Requisitos

- Windows (testado), Python **3.10+**
- Chrome instalado (fallback: Chromium do Playwright)
- Conta Gameforge / OGame

---

## Instalação

```powershell
cd meu-bot-ogame
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

---

## Credenciais (`.env`)

1. Copie os exemplos e edite:

```powershell
copy .env.example .env
copy settings.example.json settings.json
```

Ajuste em `settings.json` as coordenadas `Origin` / `Target` / `Expeditions.TopScore` da sua conta. Esse arquivo **não** vai pro git.

2. Preencha no `.env` (nunca commitar):

| Variável | Obrigatório | Descrição |
|----------|-------------|-----------|
| `EMAIL` | sim | Login Gameforge |
| `PASSWORD` | sim | Senha Gameforge |
| `UNIVERSE` | sim | Nome do universo (como na lista do lobby) |
| `LANG` | recomendado | Comunidade, ex.: `br` |
| `LOBBY` | não | Default `lobby` |
| `TELEGRAM_TOKEN` | p/ Telegram | Token do [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | p/ Telegram | ID do chat (após `/start`; ver abaixo) |
| `HEADLESS` | não | `1` / `0` — sobrescreve `General.Headless` |
| `SETTINGS_PATH` | não | Path do JSON (default `settings.json`) |
| `CAPTCHA_API_KEY` | não | Reservado; captcha hoje é manual no desktop |

Exemplo mínimo:

```env
EMAIL=seu@email.com
PASSWORD=sua_senha
UNIVERSE=NomeDoUniverso
LANG=br
LOBBY=lobby
```

Credenciais do `.env` sobrescrevem o bloco `Credentials` do `settings.json` no load.

**Features / comportamento** ficam em `settings.json` (hot-reload do path configurado). Segredos só no `.env`.

---

## Executar

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

- Abre Chrome/Chromium, faz login, entra no universo e sobe a TUI.
- Captcha / login incompleto: resolva na janela do browser no desktop.
- Teclas úteis no terminal: `b` = browser/inspect, `r` = reconfirm sessão.
- `Ctrl+C` encerra (e avisa no Telegram se estiver ativo).

Demo da TUI sem login:

```powershell
python tui.py
```

Logs diários: `logs/YYYY-MM-DD.log`. Sessão do browser: `session_*.json` (não commitar).

### Produção (PC sozinho)

- Deixe o PC acordado (sem sleep/hibernação agressiva).
- `General.Headless: true` no `settings.json` (ou `HEADLESS=1`).
- Primeiro login / captcha ainda exige você no desktop; depois a sessão costuma subir headless.
- Opcional: Task Scheduler / Startup para `python main.py` após o login do Windows.
- Checklist remoto: [`docs/TELEGRAM_REMOTE.md`](docs/TELEGRAM_REMOTE.md) (Parte B).

---

## Workers / features

Cada épico ≈ um módulo em `features/`, ligado em `compose.py`. Liga/desliga e afina em `settings.json` (`"Active": true|false`).

| Worker | Settings | O que faz |
|--------|----------|-----------|
| Overview | (sempre) | Health DOM / wake do Brain |
| SleepMode | `SleepMode` | Pausa workers na janela de sono; fleet-save opcional |
| Defender | `Defender` | Detecta ataque, alarme, Telegram, evacuate |
| Expeditions | `Expeditions` | Mantém slots de expedição |
| AutoFarm | `AutoFarm` | Farm de inativos |
| AutoHarvest | `AutoHarvest` | Recicla debris |
| AutoColonize | `AutoColonize` | Coloniza targets |
| AutoDiscovery | `AutoDiscovery` | Missões Discovery |
| AutoMine | `Brain` + `Brain.AutoMine` | Minas / facilidades / lua |
| AutoResearch | `Brain` + `Brain.AutoResearch` | Pesquisas clássicas |
| Lifeform AutoMine | `Brain` + LF AutoMine | Prédios lifeform |
| Lifeform AutoResearch | `Brain` + LF AutoResearch | Techs lifeform |
| AutoCargo | `Brain` + `Brain.AutoCargo` | Constrói cargos |
| AutoRepatriate | `Brain` + `Brain.AutoRepatriate` | Recolhe recursos |
| Transports | `Brain.Transports` | Manda recursos faltantes entre celestiais |

Master switch da economia: `Brain.Active`. Slots globais: `General.SlotsToLeaveFree`.

Detalhe de tasks/status e chaves: [`FEATURES.md`](FEATURES.md).

---

## Telegram

Arquitetura: o bot roda no **PC**; o celular só recebe alertas e manda `/comandos`. Login/captcha continua no desktop. Guia longo: [`docs/TELEGRAM_REMOTE.md`](docs/TELEGRAM_REMOTE.md).

### 1. Criar o bot

1. Abra [@BotFather](https://t.me/BotFather) → `/newbot`.
2. Escolha nome e username (deve terminar em `bot`).
3. Copie o **token**.

### 2. `.env` + `settings.json`

```env
TELEGRAM_TOKEN=123456:ABC...
# TELEGRAM_CHAT_ID=  ← opcional no 1º boot; o bot pede após /start
```

Em `settings.json`:

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

Alertas de ataque: `Defender.TelegramMessenger.Active` (+ `CooldownMinutes`).

### 3. Ligar o chat

1. `python main.py` (com `TELEGRAM_TOKEN` setado).
2. No Telegram, abra o bot e envie **qualquer mensagem** (ex.: `/start`).
3. O bot responde com o `chat_id` e grava um bind local; coloque no `.env`:

```env
TELEGRAM_CHAT_ID=123456789
```

4. Reinicie o processo. Só esse chat_id recebe comandos/notificações.

Sem token ou com `TelegramMessenger.Active: false`, o Telegram fica no-op.

### Comandos

| Comando | Efeito |
|---------|--------|
| `/start` | Lista comandos |
| `/ping` | `pong` + uptime |
| `/status` | sessão, headless, inspect/recover, ataque |
| `/pause` | pausa workers |
| `/resume` | retoma (se não estiver em inspect/recover) |

Auto-ping a cada `TelegramAutoPing.EveryHours` (se ativo).

### Quando pedir login no desktop

1. Complete login/captcha na janela Chrome do Playwright.
2. Tecla `b` no terminal **ou** `/resume` no Telegram (sessão já ok).
3. Confirme alerta de sessão retomada / logs `telegram: …` em `logs/`.

---

## Layout

| Path | Função |
|------|--------|
| `main.py` / `compose.py` | login, sessão, wire workers |
| `runtime.py` | agenda ticks |
| `features/` | decisão + tick por feature |
| `game/` | adapter Playwright (DOM) |
| `config.py` | `.env` + `settings.json` |
| `tui.py` | dashboard terminal |
| `telegram_notify.py` | notify + polling de comandos |
| `settings.example.json` | template dos workers (copie → `settings.json`) |
| `.env` | credenciais (não versionar) |
| `docs/` | FOCUS, Telegram, handoffs |
| `FEATURES.md` | plano / paridade TBot |

---

## Segurança

- Não commitar `.env`, `session_*.json`, tokens ou senhas.
- Telegram só aceita o `TELEGRAM_CHAT_ID` configurado (whitelist).
- Trate o PC do bot como o “servidor”: sem processo vivo, sem resposta no Telegram.
