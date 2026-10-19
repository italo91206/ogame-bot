# FOCUS.md — perfis de workers (rascunho)

Não é épico em [`FEATURES.md`](../FEATURES.md) ainda.  
Workers continuam scripts determinísticos. Focus **não** decide o que construir nem clica no jogo — só aplica um **pacote de settings** (Active / subtoggles / leaves).

Guia Telegram (transporte): [`TELEGRAM_REMOTE.md`](TELEGRAM_REMOTE.md).

---

## Definição

**Focus = perfil do bot** (nome + preset de workers e sub-módulos).

Espelho mental: SleepMode já “mata” features por janela de tempo; Focus faz o mesmo por **intenção humana** (`normal`, `guerra`, `férias`, …).

| Faz | Não faz |
|-----|---------|
| Ligar/desligar workers e subtoggles de uma vez | Política de mina/pesquisa / “o que upar” |
| Gravar o pacote via ponte → `settings.json` | DOM / Playwright |
| Sinalizar o modo ativo na TUI / log | LLM, world-state cache, scheduler global |

Aplicar: `focus_apply(modo)` ← Telegram `/focus guerra` **e/ou** comando no terminal; hot-reload se o preset gravar settings. Um contrato → N transportes (`control.py` já é a semente).

**Não aprofundar além do preset** até doer. World state / agente ficam fora do caminho crítico (ver [Depois, se doer](#depois-se-doer)).

---

## Modos

Nomes TBD (`Focus` vs `Brain.Mode` — um campo só). Conteúdo dos presets é tabela ↔ chaves reais do `settings.json`.

### `normal` (default operacional)

Rotina atual: o que o humano já configurou como “dia a dia” (AutoMine / AutoResearch / transports / Expeditions / etc. conforme `settings.json`).

Focus `normal` **não** inventa uma economia nova — restaura / mantém o pacote “padrão” definido pelo usuário (ver `Focus.Default` abaixo).

### `guerra`

Humano está ativo no jogo; o bot **não compete** por recursos nem slots, mas mantém **vigilância** do império.

| Peça | Esperado |
|------|----------|
| Spenders (mine, research, LF, expo, colonize, discovery, farm, harvest, cargo, repatriate, transports, …) | **off** |
| Slots | livres para o humano (`SlotsToLeaveFree` alto / spenders off) |
| `Defender.Active` | **on** |
| `Defender` notify / Alarm / Telegram | **on** (avisos) |
| `Defender.Autofleet` | **off** — sem evac automática |
| `SleepMode` / `AutoFleetSave` | **off** — não mexer na frota por sono |

Subentendido: você joga; o bot só checa segurança e notifica.

### `férias`

Dois caminhos, **mesmo efeito** no Runtime:

1. **Inferido pelo DOM** — bot detecta modo férias OGame (`game/vacation.py` / `#advice-bar`).
2. **Preset manual** — `/focus férias` (ou equivalente): pacote vazio (todos os workers off).

Comportamento:

- Processo **continua up** (sessão, TUI, Telegram, watchdog).
- **Todos** os workers em off → nenhum tick de feature gasta recurso / envia frota.
- Flag explícita na TUI **e** no log: `modo férias ativado` (hoje: `ctx["vacation"]` + banner TUI; unificar mensagem).
- Runtime: gate que bloqueia ticks enquanto férias estiver ativo (seed: `runtime.py` + `ctx["vacation"]`).

#### Entrada

| Fonte | Ação |
|-------|------|
| DOM: férias **liga** | aplicar preset `férias` (workers off) + flag TUI/log; persistir Active=false via ponte |
| Comando humano `/focus férias` | idem (preset vazio) |

#### Saída (só via DOM, se o bot segue rodando)

Quando o DOM indicar que **saiu** do modo férias OGame:

- limpar flag `modo férias ativado`
- aplicar o **modo padrão pós-férias** (`Focus.Default`, nome TBD) — **não** deixar settings “como ficou” no escuro
- default sugerido: `normal` (passivo / rotina); valor **configurável** pelo usuário

Exemplo de config (rascunho de chave):

```json
"Focus": {
  "Current": "normal",
  "Default": "normal"
}
```

`Default` = para onde voltar ao sair do férias DOM (e, se útil, ao boot sem Current).  
Ainda aberto: se `/focus férias` manual deve ser “preso” até comando humano, ou o DOM manda sempre.

#### Seed já feito (sem Focus completo)

- Percepção DOM: `game/vacation.py`
- Desliga workers: `control.disable_all_for_vacation` + grava settings
- Gate: `ctx["vacation"]` → Runtime não agenda ticks de feature
- **Gap vs este doc:** ao sair do férias OGame hoje **não** restaura `Focus.Default` — só limpa o gate; Active dos workers ficam false até toggle manual / futuro `focus_apply(Default)`

---

## Tabela-alvo (rascunho; ajustar chaves)

| Chave / worker | `normal` | `guerra` | `férias` |
|----------------|----------|----------|----------|
| Spenders (Brain mine/research/LF, Expo, Colonize, Discovery, Farm, Harvest, Cargo, Repatriate, Transports, …) | conforme pacote default do user | off | off |
| `Defender.Active` | conforme default | on | off |
| `Defender.Autofleet.Active` | conforme default | **off** | off |
| `Defender` Alarm / Telegram | conforme default | on | off |
| `SleepMode` / AutoFleetSave | conforme default | off | off |
| Flag TUI/log férias | — | — | `modo férias ativado` |

`normal` = snapshot/pacote nomeado do que o user considera rotina — não “tudo on”.

---

## Ponte mínima

Já existe semente em `control.py` (toggle Active, vacation disable-all).

Ops Focus:

| Op | Notas |
|----|-------|
| `focus_apply(modo)` | aplica tabela do modo; grava settings; atualiza `Focus.Current` |
| `focus_get` | Current + Default + se DOM férias |
| toggles pontuais | continuam; durante `férias` DOM: TBD se override humano é respeitado ou re-aplicado no próximo refresh |

Telegram + terminal chamam a **mesma** op — sem fork de lógica.

---

## Fora de escopo (de propósito)

- LLM / agente escolhendo o que upar
- World-state cache como pré-requisito do Focus
- Scheduler de prioridade global
- Focus que “joga guerra” (ataque, fleetsave ofensivo) — só libera slots e vigia
- Parar o processo no férias (bot up, workers off)

---

## Ordem sugerida

1. Congelar nomes (`Focus.Current` / `Default`) + tabela preset ↔ chaves
2. `focus_apply` em cima de `control.py` (guerra + normal + férias)
3. Férias DOM: entrada já seed → **saída restaura `Focus.Default`**
4. Wire Telegram `/focus` + sinal TUI/log unificado
5. (Depois) mais modos só se precisar (`colonize`, …)

---

## Depois, se doer

Não bloqueiam Focus:

- **World state** — cache do que o bot já viu (status remoto sem reparse)
- **Agente** — intenção → `focus_apply` / toggles; nunca recebe `Page`
- Brain parity (wake, DOIR) — continua em FEATURES; Focus só escolhe *o que pode correr*

---

## Aberto

- [ ] Nome estável: `Focus` vs `Brain.Mode`
- [ ] Conteúdo exato do pacote `normal` (snapshot do settings atual vs lista fixa)
- [ ] Valor default de `Focus.Default` (`normal`?)
- [ ] `/focus férias` manual: o DOM pode “acordar” sozinho ao sair do férias OGame?
- [ ] Override humano (tecla `w`) durante férias DOM: respeitar ou re-aplicar preset no refresh?
- [ ] Lista fina de spenders no modo `guerra` (inclui AutoHarvest? Discovery?)

## Gatilhos pra virar épico em FEATURES

- [ ] Tabela preset ↔ chaves fechada para `normal` / `guerra` / `férias`
- [ ] `focus_apply` + persist `Current`/`Default`
- [ ] Saída DOM férias → aplica `Default` sem restart
- [ ] TUI/log: `modo férias ativado` estável
- [ ] Prova: `/focus guerra` (ou terminal) sem restart; Defender on, Autofleet off, spenders off

Até lá: âncora de discussão.
