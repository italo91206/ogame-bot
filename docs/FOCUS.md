# FOCUS.md — estado local, ponte de controle e agente (rascunho)

Notas para o futuro. Não é épico em [`FEATURES.md`](../FEATURES.md) ainda.  
Workers continuam scripts determinísticos; “inteligência” e intenção humana entram **acima** deles, via ponte — não no `tick`.

Guia Telegram (transporte): [`TELEGRAM_REMOTE.md`](TELEGRAM_REMOTE.md).

---

## Problema

Cada worker otimiza o próprio tick (expo enche frota, Brain gasta recurso, Colonize espera slot).  
Do lado humano a pergunta é outra: *qual é o foco agora?* (farm / construir / guerra / colonizar) — e *o que o bot sabe do universo sem reabrir o DOM?*

Hoje:

- ligar/desligar é manual (`Active`, leaves, SleepMode, IsolateExpeditions)
- status “verdadeiro” exige parse Playwright de novo
- atalhos de terminal e Telegram (E16) tendem a virar caminhos paralelos se não houver um contrato comum

---

## Princípio

| Camada | Faz | Não faz |
|--------|-----|---------|
| `game/` + workers + Runtime | Parse/click, regras, slots, agenda | Escolher estratégia; falar com humano/LLM |
| **World state** | Cache local + diff do que o bot já viu | Ser verdade absoluta sem revalidar |
| **Ponte de controle** | Ops tipadas (status, toggle, focus, …) | DOM direto; política de mina/pesquisa |
| Focus / presets | Pacotes de settings via ponte | Clicar no jogo |
| Transportes (Telegram + terminal) | Entregar a mesma ponte ao humano | Lógica de jogo própria |
| Agente (opcional) | Intenção → lê state → chama ponte | Substituir workers no loop |

LLM **fora** do tick. Bot de fundo nunca depende de modelo pra até a próxima mina.  
Agente / humano **nunca** recebem `Page` — só state + ponte.

### Transportes (simultâneos)

- **Telegram** = meio de comunicação **principal** (remoto, alertas, comandos).
- **Terminal** (TUI / teclas / stdin) = meio **local** equivalente, no mesmo processo.
- Os dois ficam **ativos ao mesmo tempo**: um comando no Telegram não bloqueia atalho no terminal, e vice-versa.
- Ambos só chamam a **mesma ponte**; não duplicar “set Active” em três sítios (TUI vs Telegram vs hot-reload ad hoc).
- Hot-reload de `settings.json` continua válido; a ponte é a API preferida para mutações sob demanda.

---

## Fase 0 — World state (prioridade)

Cache local (memória; dump JSON opcional para inspeção/agente) atualizado como **efeito colateral** de parses/ações bem-sucedidas em `game/` (overview, filas, fleets, resources, …).

Fatias mínimas (TBD fino):

| Fatia | Conteúdo típico |
|-------|-----------------|
| celestials | lista + tipo + coords |
| resources | metal/cristal/deut (+ produção se houver) **por planeta/lua** |
| fleets | estacionada **por celestial** + em voo (missão, ETA, origem/destino) |
| queues | build / research / shipyard (+ ETA) |
| slots | livres / total / leaves efetivos |
| techs / buildings | níveis já lidos (quando o worker/parse trouxe) |
| meta | `updated_at` por fatia, fonte do último write, staleness |

**Diff curto** (janela pequena, não event-sourcing): o que mudou desde o último snapshot — para LLM/humano não relerem o mundo inteiro.

Regras:

- Writers claros (após parse/ação OK); merge por fatia, não “um blob opaco”.
- State é aproximado; **ação crítica** (enviar frota, click destrutivo) revalida no `game/` se a fatia estiver stale ou se o op exigir verdade fresca.
- Readers baratos: TUI, `/status`, agente, decisões de *config* — sem DOM.

---

## Fase 1 — Ponte de controle

Módulo (nome TBD: `bridge/` / `control/`) = catálogo de funções tipadas, cada uma com:

- nome + **descritivo** (texto estável → futuro tool-schema do agente)
- inputs / outputs
- risco: `read` | `config` | `fleet` | `destructive`
- fonte: `state` | `state+fresh-DOM` | só DOM
- side effects (grava `settings.json`? wake worker? notifica?)

Ops iniciais (exemplos, não API final):

| Op | Risco | Notas |
|----|-------|-------|
| `status` / `state_get` | read | lê world state (+ diff opcional); sem parse |
| `worker_list` | read | Active, next_in, reason (espelho TUI) |
| `worker_set_active` | config | liga/desliga worker sob demanda |
| `focus_apply` | config | aplica preset (Fase 2) |
| `settings_get` / patch pontual | config | o que o humano já faria no JSON |
| comandos sessão (`pause` / `resume` / …) | config | alinhar com E16 / terminal |

Um contrato → N transportes. Novos comandos Telegram ou teclas = thin wrappers.

---

## Fase 2 — Focus preset (burro e estável)

Campo tipo `Focus: passive | farm | war | build | colonize` (nome TBD) que só aplica um **pacote** de settings **via ponte**.

Exemplos (ajustar depois; não congelar nomes cedo):

| Focus | Expo | Colonize | Brain mine/research | Leave Expo | Notas |
|-------|------|----------|---------------------|------------|-------|
| `passive` / farm | on | off/low | on leve | alto (2+) | maximiza expo + economia |
| `colonize` | leave alto | on | on | 2–3 | headroom de frota |
| `build` | leave alto | off | on pleno | 2+ | prioriza filas / transports |
| `war` | off ou mínimo | off | mines off/low | — | cargos/defesa; frota livre |

Espelho mental: SleepMode já “mata” features por janela — Focus é o mesmo padrão, semântico.  
Aplicar: ponte (`focus_apply`) ← Telegram `/focus war` **e/ou** atalho/comando no terminal; hot-reload se o preset gravar `settings.json`.

---

## Fase 3 — Brain mais esperto (ainda determinístico)

Já no plano FEATURES; não precisa de IA. Ponteiro, não duplicar tasks aqui:

- leave por feature (Expo vs General) — **feito**
- wake drop / frota → Brain (`E04-T04`, `E03-T07`, …)
- DOIR / prioridades research (`E05-T05`, `E08-T04`)

Focus escolhe *o que* pode correr; estas tasks escolhem *o que construir* dentro do foco.

---

## Fase 4 — Agente por cima

Intenção humana (“vou atacar X”, “só farmar”) → agente:

1. Lê **world state / diff** (não parseia DOM)
2. Escolhe ou compõe preset / toggles
3. Chama a **mesma ponte** que Telegram e terminal
4. Confirma ações `destructive` (ataque, abandon, cancelar filas)

“Matar filas” = `Active: false` nos workers + (se um dia existir) cancel de builds/research — não é o LLM jogando OGame.

Contrato do agente: **só lê state e chama a ponte**; Runtime/Playwright continuam donos do DOM.

---

## Fora de escopo (de propósito)

- LLM em todo `Worker.tick`
- Agente com `Page` / seletor CSS
- Um “super Brain” que reimplementa expo/mina
- Parar o bot pra “ficar agêntico”
- Scheduler de prioridade global complexo antes de state + ponte + Focus
- Event sourcing / DB / MCP completo / WebUI como pré-requisito
- Workers confiando *só* em cache para enviar frota sem revalidar quando preciso

---

## Ordem sugerida

1. **World state** + writes a partir dos parses que já existem (overview / fleets / resources)
2. **Ponte** + wire **Telegram + terminal em paralelo** (toggle worker, status from state)
3. **Focus presets** em cima da ponte
4. Fechar parity Brain útil (wake, DOIR) em FEATURES
5. Agente fino — quando state + ponte já cobrirem o dia a dia

---

## Gatilhos pra virar épico em FEATURES

- [ ] Schema estável das fatias do world state (+ regra de stale / revalidação)
- [ ] Catálogo da ponte (ops + descritivos + risco) usado por Telegram **e** terminal sem fork de lógica
- [ ] Prova: toggle worker / `/status` sem restart; os dois transportes no mesmo processo
- [ ] Nome estável dos modos Focus + tabela preset ↔ chaves `settings.json`
- [ ] Teste: trocar focus sem restart e ver workers respeitarem no próximo tick

Até lá: este arquivo é só âncora de discussão.
