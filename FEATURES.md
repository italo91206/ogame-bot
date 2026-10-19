# meu-bot-ogame — Plano de Features (fonte: TBot)

Plano top-level para implementação futura. Features mapeadas do **TBot** (.NET + ogamed) para este projeto (Playwright / Python).

Status atual do projeto: **E00 done** (T09 Overview wake), **E01 T01+T02+T03 done**, **E02 T01+T02+T04+T05 done**, **E03 T01+T02+T04+T06+T08 done**, **E04 T01+T02+T04 done** (Transports + ArriveIn wake), **E05 core + T09+T10+T11 done**, **E06 core + T03+T04+T05 done**, **E07 core + T04+T05 done**, **E08 core + T05+T06 done**, **E09 done**, **E10 done**, **E13 T01 done**, **E14 T01+T04 done** (DOIR priorities / E14 abandon+intensive ainda `todo`).

---

## Índice / Sumário

| ID | Épico | Escopo |
|----|--------|--------|
| [E00](#e00--fundação--runtime) | Fundação / Runtime `done` | sessão, config, loop, slots, captcha |
| [E01](#e01--sleep-mode--fleet-save) | SleepMode / FleetSave `T01+T02+T03 done` | janela de sono, ghost fleet |
| [E02](#e02--defender) | Defender `T01+T02+T04+T05+T09 done` | anti-ataque, evacuate, spy/msg |
| [E03](#e03--expeditions) | Expeditions `T01+T02+T04+T06+T08 done` | manter slots de expo cheios |
| [E04](#e04--brain--orquestração) | Brain (orquestração) `T02+T04 done` | master switch + transports + ArriveIn |
| [E05](#e05--brain--automine) | Brain · AutoMine `core + T09+T10 done` | minas/facilidades/lua (+ parity `todo`) |
| [E06](#e06--brain--lifeform-automine) | Brain · Lifeform AutoMine `core + T03 done` | prédios LF + food/pop/T2/T3 |
| [E07](#e07--brain--lifeform-autoresearch) | Brain · Lifeform AutoResearch `core done` | techs LF |
| [E08](#e08--brain--autoresearch) | Brain · AutoResearch `core + T05+T06 done` | pesquisas clássicas + transports |
| [E09](#e09--brain--autocargo) | Brain · AutoCargo `done` | construir cargos |
| [E10](#e10--brain--autorepatriate) | Brain · AutoRepatriate `done` | recolher recursos |
| [E11](#e11--brain--offer-of-the-day) | Brain · Offer of the Day | oferta diária trader |
| [E12](#e12--autofarm) | AutoFarm `T01 done` | farm de inativos |
| [E13](#e13--autoharvest) | AutoHarvest `T01 done` | reciclar DFs |
| [E14](#e14--autocolonize) | AutoColonize `T01+T04 done` | colonizar / abandonar |
| [E15](#e15--autodiscovery) | AutoDiscovery `T01 done` | missões Discovery |
| [E16](#e16--plataforma--opcional) | Plataforma (opcional) | multi-instance, Telegram, WebUI, proxy |

**Legenda de status (para controle):** `todo` · `doing` · `done` · `skip`

**IDs:** `E##` = épico · `E##-T##` = task

---

## E00 — Fundação / Runtime `done`

**O que é:** camada base sem a qual nenhum worker roda.  
**O que faz:** autentica, mantém sessão no universo, carrega config, agenda features com intervalos aleatórios, reserva slots de frota, trata captcha.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E00-T01 | Credenciais / lobby | `done` | Login Gameforge + entrar universo | `Credentials` + `.env` |
| E00-T02 | Device fingerprint | `done` | Emular device consistente no browser | `Credentials.DeviceConf` |
| E00-T03 | Config loader | `done` | `.env` + `settings.json` (`reload_settings`) | `SETTINGS_PATH` |
| E00-T04 | Session loop | `done` | `Runtime` tick workers c/ intervalo random | — |
| E00-T05 | Slots livres | `done` | `slots_available` / `Runtime.can_send_fleet` | `General.SlotsToLeaveFree` |
| E00-T06 | Captcha | `done` | Pause manual se widget visível | `General.CaptchaAPIKey` (API = skip até precisar) |
| E00-T07 | Host/Port | `skip` | N/A no Playwright | — |
| E00-T08 | Celestial helpers | `done` | Parse + switch planet/moon | `Coords` / `Celestial` |
| E00-T09 | Overview → Brain wake | `done` | Se stock no scan saltou vs projeção (+drop/incoming), antecipar tick Brain (`Runtime.wake`); `have ≥ cost` pendente → **E04-T04** | — |
| E00-T10 | DOM health / re-login | `done` | `last_good` planetList + uptime; se stale → browser headed p/ login | `dom_health.STALE_AFTER_S` |

---

## E01 — SleepMode / FleetSave `T01+T02+T03 done`

**O que é:** modo sono + salvamento de frota.  
**O que faz:** pausa automações entre `GoToSleep` e `WakeUp`; opcionalmente faz fleet-save (deploy/harvest + recall) ao dormir; pode adiar sono se há frotas voltando; logout opcional.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E01-T01 | Janela de sono | `done` | Pausar features no intervalo (`sleepmode.py` + gate `Runtime`) | `SleepMode.Active`, `GoToSleep`, `WakeUp` |
| E01-T02 | Prevent fleets | `done` | Adiar sono se eventFleet chega dentro da janela | `PreventIfThereAreFleets` |
| E01-T03 | AutoFleetSave | `done` | Deploy/Harvest/Spy/Colonize + recall (`fleetsave.py`); `OnlyMoons` filtra em `sleepmode.py`; deploy dest prefere outras luas | `AutoFleetSave.{Active,OnlyMoons,DeutToLeave,Recall,DefaultMission}` |
| E01-T04 | Logout on sleep | `skip` | Logout comentado no TBot; sessão Playwright fica | `LogoutOnSleep` |
| E01-T05 | Notify | `todo` | Avisar início/fim de sono | `SleepMode.TelegramMessenger.Active` → **E16** |

---

## E02 — Defender `T01+T02+T04+T05+T09 done`

**O que é:** vigilância de ataques.  
**O que faz:** polling de fleets hostis; alarme; spy/msg no atacante; evacuate (autofleet); whitelist; ignora probes/ataques fracos/baixo valor; defesa de mísseis; atividade random em “Home”.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E02-T01 | Poll ataques | `done` | eventList AJAX → hostis (`defender.py`) | `Active`, `CheckIntervalMin/Max` (segundos) |
| E02-T02 | Filtros | `done` | probes / fraco / baixo valor | `IgnoreProbes`, `IgnoreWeakAttack`, `WeakAttackRatio`, `IgnoreAttackIfIHave.{Active,MinResourcesToSave,MinFleetToSave}` |
| E02-T03 | Mísseis | `todo` | Reagir a IPM; TBot remapeia silo ABM para o **planeta** do mesmo G:S:P se o alvo for lua | `DefendFromMissiles` |
| E02-T04 | Autofleet | `done` | Evacuar via `fleetsave.py` no celestial atacado (planeta **ou** lua; não usa `OnlyMoons`) | `Autofleet.{Active,BuildCargosIfNeeded}` + `SleepMode.AutoFleetSave` |
| E02-T05 | WhiteList | `done` | Não reagir a IDs listados | `WhiteList[]` (player IDs) |
| E02-T06 | SpyAttacker | `todo` | Espionar atacante | `SpyAttacker.{Active,Probes}` |
| E02-T07 | MessageAttacker | `todo` | Mandar msg aleatória | `MessageAttacker.{Active,Messages[]}` |
| E02-T08 | RandomActivity | `todo` | Atividade fake no Home | `RandomActivity`, `Home.{Galaxy,System,Position,Type}` |
| E02-T09 | Alarm / Telegram | `done` | Beep + banner TUI vermelho + push | `Alarm.Active`, `TelegramMessenger.{Active,CooldownMinutes}` |

---

## E03 — Expeditions `T01+T02+T04+T06+T08 done`

**O que é:** automação de expedições.  
**O que faz:** mantém slots de expo ocupados a partir de 1+ origins; frota primary/secondary ou manual; pacing wait-all/majority; split de sistemas; combustível.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E03-T01 | Loop expo | `done` | Enviar próximas expos quando slot livre (1/tick) | `Active`, `Origin[]`, `SlotsToLeaveFree` (≥ General), `Min/MaxWaitNextFleet`, `Min/MaxWaitNextRound` |
| E03-T02 | Frota auto | `done` | Primary + secondary por ratio + probe/militar/PF | `PrimaryShip`, `MinPrimaryToSend`, `PrimaryToKeep`, `SecondaryShip`, `MinSecondaryToSend`, `SecondaryToPrimaryRatio`, `TopScore` |
| E03-T03 | Frota manual | `todo` | Composição fixa | `ManualShips.{Active,Ships.{...}}` |
| E03-T04 | Pacing | `done` | Esperar todas / maioria; next tick = BackIn (+ pad) | `WaitForAllExpeditions`, `WaitForMajorityOfExpeditions` |
| E03-T05 | Split systems | `todo` | Distribuir destinos em range | `SplitExpeditionsBetweenSystems.{Active,Range}` |
| E03-T06 | Extras | `done` | Ordem random, deut a bordo | `RandomizeOrder`, `FuelToCarry` |
| E03-T07 | Drop → Brain | `todo` | Ao voltar expo (ou no `BackIn`), acordar smart ticket Brain | → **E04-T04** |
| E03-T08 | Origin Type | `done` | `Origin[].Type` Planet/Moon; Origin vazio → só planetas (TBot fallback prefere planeta) | `Origin[]` |

---

## E04 — Brain · Orquestração `T02 done`

**O que é:** master switch do “cérebro” de economia.  
**O que faz:** habilita subfeatures Brain; serializa jobs Brain (1 por vez); transports compartilhados para cobrir custo de build/research.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E04-T01 | Master toggle | `done` | Ligar/desligar bloco Brain | `Brain.Active` |
| E04-T02 | Transports shared | `done` | Enviar recursos faltantes do Origin; se Origin > storage×`OverflowFactor`, enche armazém do dest (`transports.py`); Origin/dest `Type` Moon ok; `DeutToLeave` sempre no Origin (≠ `DeutToLeaveOnMoons`) | `Brain.Transports.{Active,CargoType,DeutToLeave,RoundResources,OverflowFactor,Origin}` |
| E04-T03 | Brain semaphore | `todo` | Garantir um job Brain por vez | — (runtime) |
| E04-T04 | Drop / fleet wake | `done` | Pós-transport: next tick = `ArriveIn`+jitter (`transport_retry_wait`); wait de recurso = `min(ETA, ArriveIn)` (`clamp_wait_to_incoming`); Overview drop wake já em **E00-T09**. BackIn expo/farm → **E03-T07** / **E12-T06** | — (API interna) |

---

## E05 — Brain · AutoMine

**O que é:** construção automática de minas/facilidades (planeta + lua).  
**O que faz (TBot):** caps; pick (start/DOIR/robots); energia (planta/fusão/sats); crawlers; deposit por horas/cheio; transports; timer por celestial.  
**O que fazemos:** caps + pick lazy (ratio start, sem DOIR) + energia (planta/fusão/sats) + UI `data-status`; smart ticket (countdown / ETA recursos / CheckInterval). Sem épico novo — parity = tasks abaixo (transports = E04).

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E05-T01 | Caps planeta | `done` | Limites minas/storage/facilidades | `MaxMetalMine`…`MaxSpaceDock` |
| E05-T02 | Caps lua | `done` | Base / robots / phalanx / jump / yard; pick lua: Base(se 1 field)→Robots→Jump→Phalanx→Yard (`MaxLunarShipyard` costuma 0) | `MaxLunarBase`, `MaxLunarShipyard`, `MaxLunarRoboticsFactory`, `MaxSensorPhalanx`, `MaxJumpGate` |
| E05-T03 | Pick básico | `done` | Energia→planta/fusão; start ratio; mines min-level; robots/nanites; deposit se UI `on`; luas = facilities-only | `OptimizeForStart`, `PrioritizeRobotsAndNanites`, `BuildDepositIfFull` |
| E05-T04 | Escopo + smart ticket | `done` | Exclude/ordem; next = min(countdown, ETA **prod** cap `CheckIntervalMax`, else intervalo) | `Active`, `RandomOrder`, `Exclude[]`, `CheckIntervalMin/Max` |
| E05-T05 | DOIR / ROI | `todo` | Parar/priorizar minas por dias de retorno (TBot `CalcDaysOfInvestmentReturn`) | `MaxDaysOfInvestmentReturn` |
| E05-T06 | Solar sats | `done` | Energia negativa → planta/fusão; senão sats (estaleiro); hangar/robôs se preciso. Terraformer-via-sats = skip | `BuildSolarSatellites` (default true) |
| E05-T07 | Crawlers | `todo` | Collector: ótimo de crawlers no estaleiro | `BuildCrawlers` |
| E05-T08 | DepositHours | `todo` | Storage preventivo (capacidade &lt; N h de prod), não só UI `on` | `DepositHours`, `BuildDepositIfFull` |
| E05-T09 | Deut lua | `done` | Inflar custo/ETA/transport em luas: `cost.deut += DeutToLeaveOnMoons` (`automine._pad_moon_deut`); UI `on` + sem reserva → wait/transport | `DeutToLeaveOnMoons` |
| E05-T10 | Transports hook | `done` | Pedir recursos ao Origin quando ETA impossível/lento | `AutoMine.Transports.Active` → **E04-T02** |
| E05-T11 | Smart ticket drop | `done` | `min(ETA, ArriveIn)` + pós-send ArriveIn (**E04-T04**); BackIn expo/farm ainda via **E03-T07** / **E12-T06** | — |

**vs TBot (não vira épico):** worker por celestial — nosso 1 worker varre todos + `min(wait)`; ok até multi-planet doer. ETA prod já existe; frota/expo/drop = **E05-T11** / **E04-T04**. Abandonar colônia = E14, não AutoMine.

---

## E06 — Brain · Lifeform AutoMine `core + T03+T04 done`

**O que é:** upgrade de prédios Lifeform.  
**O que faz (TBot):** food/pop/starving/T2/T3 + cheapest ConvertedDeut; transports.  
**O que fazemos:** só prédios já ≥1; caps por slot; crystal gate; `PreventIfMoreExpensiveThanNextMine`; smart ticket; UI `data-status`. Sem épico novo — parity = tasks abaixo.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E06-T01 | Gate + caps | `done` | Threshold + max levels por slot | `StartFromCrystalMineLvl`, `MaxBasePopulationBuilding`, `MaxBaseFoodBuilding`, `MaxBaseTechBuilding`, `MaxT2Building`, `MaxT3Building`, `MaxBuilding6..12` |
| E06-T02 | Regras core | `done` | Exclude, prevent expensive, interval, smart ticket | `Active`, `Exclude[]`, `PreventIfMoreExpensiveThanNextMine`, `CheckIntervalMin/Max` |
| E06-T03 | Food/pop/T2/T3 | `done` | Parse `#population_box` → starving/willStarve → food (slot2); foodForMore/full → pop (slot1); NeedsMoreT2/T3 → slots 4/5; else cheapest ≥1. Sem peek ConvertedDeut / living-space cost do TBot | — |
| E06-T04 | Transports hook | `done` | Pedir recursos ao Origin | `Transports.Active` → **E04-T02** |
| E06-T05 | Smart ticket drop | `done` | Reusar **E04-T04** ArriveIn | — |

---

## E07 — Brain · Lifeform AutoResearch `core + T04 done`

**O que é:** pesquisa automática de techs Lifeform.  
**O que faz (TBot):** techs ≥1 até caps; swap cheaper ConvertedDeut; transports.  
**O que fazemos:** techs ≥1 sob `MaxTechs11..36`; pick por nível baixo; smart ticket. Sem épico novo — parity = tasks abaixo.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E07-T01 | Caps techs | `done` | Níveis máximos por grupo | `MaxResearchLevel`, `MaxTechs11..16`, `MaxTechs21..26`, `MaxTechs31..36` |
| E07-T02 | Regras core | `done` | Exclude, interval, smart ticket | `Active`, `Exclude[]`, `CheckIntervalMin/Max` |
| E07-T03 | Cheaper swap | `todo` | `GetLessExpensiveLFTechToBuild` via peek custos | — |
| E07-T04 | Transports hook | `done` | Pedir recursos ao Origin | `Transports.Active` → **E04-T02** |
| E07-T05 | Smart ticket drop | `done` | Reusar **E04-T04** ArriveIn | — |

---

## E08 — Brain · AutoResearch `core done`

**O que é:** pesquisas clássicas.  
**O que faz (TBot):** Target (fallback maior lab); caps; `GetNextResearchToBuild` (OptimizeForStart / EnsureExpoSlots / cheapest deut); prioridades DOIR Astro/Plasma/Energy + IRN time; transports.  
**O que fazemos:** caps + pick TBot (start + expo slots + cheapest) + Target/lab + UI `data-status` + smart ticket (countdown / ETA / CheckInterval). Sem épico novo — parity = tasks abaixo.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E08-T01 | Caps techs | `done` | Limites por tecnologia | `MaxEnergy/Laser/Ion/Hyperspace/Plasma`, drives, `MaxEspionageTechnology`, `MaxComputerTechnology`, `MaxAstrophysics`, `MaxIntergalacticResearchNetwork`, weapons/shield/armour |
| E08-T02 | Prioridades core | `done` | `OptimizeForStart` + `EnsureExpoSlots` + cheapest ConvertedDeuterium | `OptimizeForStart`, `EnsureExpoSlots` |
| E08-T03 | Escopo + smart ticket | `done` | Target / maior lab; next = min(countdown, ETA cap `CheckIntervalMax`, else intervalo) | `Active`, `Target`, `CheckIntervalMin/Max` |
| E08-T04 | Prioridades DOIR | `todo` | Plasma/Astro/Energy via DOIR + IRN se mais rápido (TBot worker) | `PrioritizeAstrophysics`, `PrioritizePlasmaTechnology`, `PrioritizeEnergyTechnology`, `PrioritizeIntergalacticResearchNetwork` |
| E08-T05 | Transports hook | `done` | Pedir recursos ao Origin quando faltar | `AutoResearch.Transports.Active` → **E04-T02** |
| E08-T06 | Smart ticket drop | `done` | Reusar **E04-T04** ArriveIn | — |

---

## E09 — Brain · AutoCargo `done`

**O que é:** construção de cargos.  
**O que faz:** build cargos até caps / capacidade de storage; skip se transport incoming.  
**Não faz:** calcular “só o necessário para o próximo Brain Transport” — isso é estoque por caps; Transports só usa o que já existe.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E09-T01 | Build cargos | `done` | Construir até limites (`autocargo.py`) | `CargoType`, `MaxCargosToBuild`, `MaxCargosToKeep`, `LimitToCapacity` |
| E09-T02 | Regras | `done` | Moons, exclude, skip transport, interval | `Active`, `ExcludeMoons`, `RandomOrder`, `SkipIfIncomingTransport`, `Exclude[]`, `CheckIntervalMin/Max` |

---

## E10 — Brain · AutoRepatriate `done`

**O que é:** recolhimento periódico de recursos.  
**O que faz:** transporta recursos para Target quando acima do mínimo; deixa deut; skip moons/incoming.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E10-T01 | Collect loop | `done` | Haul → Target (`autorepatriate.py`, `send_fleet` mission 3) | `Active`, `MinimumResources`, `Target`, `CargoType` |
| E10-T02 | Deut / filters | `done` | Leave deut, exclude, moons, skip | `LeaveDeut.{OnlyOnMoons,DeutToLeave}`, `ExcludeMoons`, `SkipIfIncomingTransport`, `Exclude[]`, `RandomOrder`, `CheckIntervalMin/Max` |

---

## E11 — Brain · Offer of the Day

**O que é:** compra da oferta diária do trader.  
**O que faz:** tenta comprar; para se ok/já comprado; retry em erro.

| ID | Task | O quê | Configurabilidade |
|----|------|-------|-------------------|
| E11-T01 | Buy OOTD | Comprar oferta do dia | `Brain.BuyOfferOfTheDay.{Active,CheckIntervalMin/Max}` |

---

## E12 — AutoFarm `T01 done`

**O que é:** farm de inativos.  
**O que faz:** scan ranges → spy → atacar alvos lucrativos com cargos; filtros de rank/loot/fuel/slots/tempo; opcional build probes/cargos.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E12-T01 | Scan + spy | `done` | Varredura galaxy + sondagem (`autofarm.py`, `game/galaxy.py`, `send_fleet`) | `ScanRange[]`, `Exclude[]`, `NumProbes`, `KeepReportFor`, `TargetsProbedBeforeAttack`, `Origin[]`, `SlotsToLeaveFree` |
| E12-T02 | Attack | `todo` | Enviar farm fleet | `CargoType`, `FleetSpeed`, `MinCargosToKeep/Send`, `CargoSurplusPercentage`, `MinimumResources`, `PreferedResource` |
| E12-T03 | Filtros | `todo` | Rank, tempo, fuel, slots | `MinimumPlayerRank`, `MaxFlightTime`, `MaxWaitTime`, `MinLootFuelRatio`, `MaxSlots`, `SlotsToLeaveFree`, `ExcludeMoons` |
| E12-T04 | Build aux | `todo` | Build probes/cargos se faltar | `BuildCargos`, `BuildProbes` |
| E12-T05 | Pacing | `todo` | Intervalo do worker (parcial: CheckInterval já no T01) | `Active`, `CheckIntervalMin/Max` |
| E12-T06 | Drop → Brain | `todo` | Ao voltar farm (loot no planeta), acordar smart ticket Brain | → **E04-T04** |

---

## E13 — AutoHarvest `T01 done`

**O que é:** reciclagem de debris.  
**O que faz:** recicla DF próprio e/ou deep space (expo) acima de thresholds; respeita range de split de expo quando aplicável.  
**O que fazemos:** galaxy debris → recyclers (own DF) / pathfinders (pos.16); origem prefer lua no mesmo slot; leave slots via `General.SlotsToLeaveFree` (`features/autoharvest.py`).

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E13-T01 | Harvest loop | `done` | Enviar recyclers/PF | `Active`, `HarvestOwnDF`, `HarvestDeepSpace`, `MinimumResourcesOwnDF`, `MinimumResourcesDeepSpace`, `CheckIntervalMin/Max` |

---

## E14 — AutoColonize `T01+T04 done`

**O que é:** colonização automática.  
**O que faz:** envia colony ships para ranges; abandon de planetas ruins (fields/temp); modo intensive research (pressionar slots Astro).  
**O que fazemos:** slots Astro vs planetas; build 1 CS se faltar; 1 colonize/tick em Targets vazios (`features/autocolonize.py`). Abandon / intensive = tasks abaixo.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E14-T01 | Colonize | `done` | Enviar CS para Targets (+ build CS) | `Active`, `Origin`, `Targets[{Galaxy,Start/EndSystem,Start/EndPosition,MaxPlanets}]`, `RandomPosition`, `SlotsToLeaveFree` |
| E14-T02 | Abandon | `todo` | Abandonar planeta ruim | `Abandon.{Active,MinFields,Min/MaxTemperatureAcceptable}` |
| E14-T03 | Intensive research | `todo` | Manter pressão em slots | `IntensiveResearch.{Active,MaxSlots,Min/MaxWaitNextFleet}` |
| E14-T04 | Pacing | `done` | Intervalo | `CheckIntervalMin/Max` |

---

## E15 — AutoDiscovery `T01 done`

**O que é:** missões Discovery.  
**O que faz:** envia Discovery a partir do Origin (ordem por distância); blacklist de falhas; caps de slots/falhas; respeita SleepMode e slots livres.  
**O que fazemos:** `sendDiscoveryFleet` AJAX (sem naves); custo 5k/1k/500; blacklist sessão (fail 1d / ok 7d); SleepMode via Runtime.

| ID | Task | Status | O quê | Configurabilidade |
|----|------|--------|-------|-------------------|
| E15-T01 | Discovery loop | `done` | Enviar missões Discovery (`autodiscovery.py`) | `Active`, `Origin`, `MaxSlots`, `MaxFailures`, `CheckIntervalMin/Max` (+ `General.SlotsToLeaveFree`, SleepMode) |

---

## E16 — Plataforma (opcional)

**O que é:** infra multi-conta / controle remoto / UI — presente no TBot, não obrigatória no MVP Playwright.  
**O que faz:** orquestra várias instâncias; Telegram para alertas/comandos; WebUI de settings/logs; proxy outbound.  
**Guia Telegram:** [`docs/TELEGRAM_REMOTE.md`](docs/TELEGRAM_REMOTE.md)

| ID | Task | O quê | Configurabilidade |
|----|------|-------|-------------------|
| E16-T01 | Multi-instance | Várias contas / aliases | `settings.json` → `Instances[].{Alias,Settings}` |
| E16-T02 | Telegram | Alertas + comandos + `notify_down` + heartbeat/`bot_watchdog.py` (`doing`) | `TelegramMessenger` / `TelegramAutoPing` / `TelegramWatchdog` + `.env` — `docs/TELEGRAM_REMOTE.md` |
| E16-T03 | WebUI | Editar settings + logs | `WebUI.{Enable,Urls,MaxLogsToShow}` |
| E16-T04 | Proxy outbound | HTTP/SOCKS5 | `General.Proxy.{Enabled,Address,Type,Username,Password,LoginOnly}` |
| E16-T05 | Fleet helpers manuais | Deploy/ghost/jumpgate/auction via comando | comandos Telegram (não worker timed) |

---

## Primeira lua — dinâmica vs TBot

Plumbing de celestial (parse/switch/Type) já cobre lua. O que muda na prática:

| Worker | Comportamento com lua | Ação típica pós-lua |
|--------|----------------------|---------------------|
| **E01 Fleetsave** | `OnlyMoons` (nosso default `false`; TBot sample `true`) + deploy prefere dest lua | Decidir se sleep salva só luas ou todos |
| **E02 Defender** | Evacua o celestial atacado (lua incluso); IPM→ABM no planeta = **E02-T03** | — |
| **E03 Expo** | Só usa lua se `Origin[].Type=Moon` | Mover frota expo + setar Origin Moon |
| **E04 Transports** | Dest lua ok (fund lunar build); Origin ainda costuma Planet | Opcional: Origin Type Moon |
| **E05 AutoMine** | Já varre luas (caps/pick + **E05-T09** deut) | Revisar `DeutToLeaveOnMoons` / caps |
| **E09 AutoCargo** | `ExcludeMoons: true` → não builda cargos na lua | Flip se quiser hangar/cargos na lua (`MaxLunarShipyard` > 0) |
| **E10 Repatriate** | Inclui luas; `LeaveDeut.OnlyOnMoons` | Ajustar `DeutToLeave` vs fleetsave |
| **E12 Farm** | Origin prefere lua no spy; `ExcludeMoons` alvo = **E12-T03** | — |
| **E13 Harvest** | Prefer recyclers/PF da lua no mesmo slot | `done` (T01) |

Prioridade pós-lua: config (`OnlyMoons` / Origin expo / ExcludeMoons cargo / valor de `DeutToLeaveOnMoons`).

---

## Ordem sugerida (lazy)

1. **E00** (já parcialmente: login) → sessão estável + config + loop  
2. **E05 / E08 / E10** — economia básica  
3. **E03** — expos (+ **E03-T07** drop wake quando Brain já tiver **E04-T04**; Origin Moon se frota na lua)  
4. **E02** — defesa  
5. **E01** — sono / fleetsave (`OnlyMoons` se frota só na lua)  
6. Restante Brain → Farm (**E12-T06**) → Harvest (prefer moon origin) → Colonize → Discovery  
7. **E04-T04 / E05-T11** (e clones E06–E08) — assim que Expo/Farm/Overview puderem sinalizar drop  
8. **E16** só se precisar multi-conta / remoto  

---

## Mapa rápido TBot → este plano

| TBot (`instance_settings`) | Épico |
|----------------------------|-------|
| Credentials / General / Captcha | E00 |
| SleepMode | E01 |
| Defender | E02 |
| Expeditions | E03 |
| Brain (+ Transports) | E04 |
| Brain.AutoMine | E05 |
| Brain.LifeformAutoMine | E06 |
| Brain.LifeformAutoResearch | E07 |
| Brain.AutoResearch | E08 |
| Brain.AutoCargo | E09 |
| Brain.AutoRepatriate | E10 |
| Brain.BuyOfferOfTheDay | E11 |
| AutoFarm | E12 |
| AutoHarvest | E13 |
| AutoColonize | E14 |
| AutoDiscovery | E15 |
| settings.json Telegram/WebUI/Instances | E16 |
