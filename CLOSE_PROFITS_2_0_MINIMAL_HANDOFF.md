# Close Profits 2.0 — handoff, REVIEWRONDE 5 (bovenaan; ronde 1–4 hieronder ongewijzigd als historie)

Code-commit ronde 5: `5fb66837db5ab0e27390de54f6fc4159dbd9fc7b`. Start ronde 5: `9837a05393778857b78c3126e3f4895b8fddb550`. Branch `review/close-profits-2-0-minimal-20261021`. 2.1-branch gescheiden, build 601/productie/vier accounts onaangetast, geen live-orders, geen workflow/Cloud Build, geen merge.

## R5.1 Retry met nieuwe sleutel — bewijs of beperking
Retry gebeurt uitsluitend bij de **volledige, exacte** tekst "Auto Hedge verwerkt momenteel dezelfde accountstatus; probeer de sluiting zo opnieuw" (voorheen een niet-verankerde regex; nu `===`). Bewijs (test `RetrySafetyProofTests`, bron-controle): die tekst heeft één raise-plek in `close_one_aster_position`, vóór `_begin_…manual_release`, `require_auto_hedge_close_allowed`, `begin_manual_action`, `execute_aster_leg`; de guard is dan `None`, dus er wordt niets als UNCERTAIN gemarkeerd; model-test: lease bezet → 0 orders, paar blijft HEDGED. Een nieuwe sleutel is nodig omdat de bestaande idempotentie de mislukte poging terecht als "ontvangen" markeert; de backend hervalideert `expected_quantity` en winst-/positiestatus. Alles anders stopt direct zonder retry: UNKNOWN/502 "niet opnieuw besteld", HTTP 500/502/503/504, proxy-uitval, verloren respons na uitvoering, gewijzigde hoeveelheid, onbekende lock, samengestelde of afwijkende teksten (getest). Max. 3 pogingen, 1,5 s pauze. **Beperking:** het bewijs rust op de route-bron en de berichttekst; een toekomstige route die dezelfde tekst na een order zou gebruiken zou het breken (de bron-test faalt dan).

## R5.2 Winstgrens op het sluitmoment
Verschil preview ↔ sluiting: tijdens de bevestiging en tussen sluitingen kan de winst dalen; de bestaande route toetst alleen hoeveelheid, niet winst. Oplossing zonder nieuwe PnL-engine en zonder routewijziging: **vóór elke individuele close** een verse, read-only `manual-profit-close-plan`-aanvraag (dezelfde backendplanner, strikt `> $0,50`, zelfde Aster-bron als de route). Niet meer geselecteerd → overgeslagen (geen order, getoond als "niet meer boven $0,50 winst"); live hoeveelheid ≠ preview → stop; verse controle onleesbaar → stop. **Restrisico (blijft):** tussen die controle en de order zit nog enkele honderden ms; de winst kan in dat venster zakken. Een atomaire winstcontrole zou de bestaande route moeten wijzigen (niet gedaan). Kosten: één extra GET (positions + exchange info) per positie.

## R5.3 Gewone SHORT wordt Auto Hedge-SHORT tussen selectie en uitvoering
Aangetoond risico (test faalde op de oude code): de route nam de lease alleen als het paar al beheerd was. Passeert de LONG van dezelfde munt de Auto Hedge-drempel terwijl de SHORT winst maakt (prijs daalt: beide gebeuren tegelijk), dan maakt de worker het paar aan terwijl de close loopt → SHORT verkleind zonder freeze, paar blijft HEDGED en de worker kan her-hedgen. **Fix (klein, in de route):** lease ook nemen als er een tegenovergestelde leg op dezelfde munt is én Auto Hedge aan staat (`asterPositionLossAutoHedge/{uid}.enabled`; onleesbaar = fail-safe aan), daarna posities én paar onder de lease opnieuw lezen en de bestaande freeze toepassen. Auto Hedge uit of geen tegenovergestelde leg → exact het oude, lease-vrije pad (getest). Gevolg: bij een drukke worker kan zo'n close "account bezig" (409, pre-order) geven, ook op de losse knop; de bulk probeert max. 3× opnieuw. Eerdere ronde-4-fixes (hervalidatie onder lease; worker neemt lease vóór lezen) blijven.
Opvallend: de bestaande regressiesuite (`test_aster_manual_close_contract`) ving een regressie van mijn eerste herschrijving (bron-contract van de route); hersteld door de oorspronkelijke toewijzing te behouden.

## R5.4 Echte integratie
| Onderdeel | Status |
|---|---|
| Echte FastAPI-app, Firestore-emulator, echte Auto Hedge-worker-loop, echte Aster | **NOT RUN** — `fastapi`, `google-cloud-firestore`, `firebase-admin`, `httpx`, `pytest` ontbreken; `pip download` en emulator-download geblokkeerd door de proxy (opnieuw bevestigd, niet omzeild). Nodig: netwerk naar PyPI/npm/Maven, Java 21, `firebase-tools@14.21.0`. |
| Dezelfde scenario's op echte Firestore | klaar maar **NOT RUN / ongeverifieerd**: `cloud_api/test_close_profits_2_0_firestore_emulator.py` (20 tests, SKIP zonder emulator) + `tools/run_close_profits_2_0_integration.sh`. Geschreven zonder uitvoering; kleine aanpassingen bij de eerste echte run zijn mogelijk. |
| Gelijktijdige worker + Close | gemodelleerd (lease-probe op elke order, worker maakt paar tussen lezen en order); geen echte threads van de echte worker-loop |
| Aster-mock | ledger met accept/drop-na-accept/reject; **geen** latency en **geen partial fills** gemodelleerd (de route meet resterende hoeveelheid; partial fill → mismatch → 502/stop, niet getest) |
Een in-memory model is **geen** Firestore-bewijs en wordt niet zo gerapporteerd.

## R5.5 Tests en regressies (exact)
| Suite | PASS | FAIL | SKIP | NOT RUN |
|---|---|---|---|---|
| `test_close_profits_2_0_integration` (model) | 24 | 0 | 0 | |
| `test_close_profits_2_0_firestore_emulator` | 0 | 0 | 20 | emulator |
| web `aster-close-profits-integration` (frontend→proxy→backend, model) | 11 (met httpx-stub) | 0 | 11 zonder httpx | |
| web handler/scope/short-handler/profitable | 24 | 0 | 0 | |
| backend hele map vs PR-head | PR-head 1990 pass / 21 FAIL / 73 importfouten → nu 2014 pass (+24) / 21 FAIL / 73 importfouten + 20 SKIP; per bestand identiek behalve de nieuwe bestanden | | | |
| web hele map | 150 van 152 bestanden; 2 FAIL pre-existing (`extreme-spike-settings-route-execution`, `rendered-html`) | | | |
| TypeScript-typecheck/Next-build | | | | **NOT RUN** (geen node_modules/tsc); wijziging in `aster-recent-trades.tsx` is bewust zonder impliciete `any`-callbacks geschreven |
Mutatie/failing-first: race-fix (3 tests faalden op oude code), hervalidatie-mutatie (502 + UNCERTAIN bewezen).

## R5.6 Resterende risico's
1. Geen echte infrastructuur-run. 2. Winst-venster van enkele ms (R5.2). 3. Positie-lag aan Aster-zijde na accepteren bij een volgende handmatige klik (bestaand). 4. Meer "account bezig"-weigeringen op hedged symbolen bij actieve Auto Hedge. 5. Partial fills/latency niet gemodelleerd. 6. Winst-hercontrole kost één GET per positie. 7. Publieke repo met `gha-creds-*.json` (WIF-config, geen privésleutel).

## R5.7 GO / NO-GO
Technische review: **GO** (minimale, geteste wijzigingen). Merge: **NO-GO** tot de emulator-run groen is. Productie: **NO-GO** — bewijs ontbreekt: echte Firestore-/FastAPI-/workerrun, partial-fill/latency-gedrag, atomair winstmoment.

---
# Close Profits 2.0 — definitief afronden (minimale scope)

Code-commit `98ea03cf946ee5ccbf43450f7a548bd1ed0203bd`. Branch `review/close-profits-2-0-minimal-20261021` (start `2df97e20`, basis PR #783 head `f8cd2af5`). De 2.1-branch blijft volledig gescheiden en is niet overgenomen.

## Scope (ongewijzigd leidend)
Groene knop = automatisering van de bestaande individuele Close: SHORTs met strikt > $0,50 winst (Auto Hedge-SHORTs inbegrepen), 25/50/75/100%, één bevestiging, per SHORT sequentieel `POST …/positions/{symbol}/close` met `{confirm, side:"SHORT", expected_quantity:<volledige live hoeveelheid>, percentage, idempotency_key}`; backend rekent het deel. Focus Airbag-hedge blijft uitgesloten (zoals de losse knop).

## Wat is onderzocht
Individuele route (`close_one_aster_position`), manual-release helpers (freeze → order → complete), lease, Auto Hedge-worker (`_run_uid`, `_prepare_lifecycle`), lock-guard, Next-proxy, `authenticatedRequest`, ContractRules-foutteksten.

## Concrete bevindingen
1. **Dode skip-regel (functioneel, frontend).** PR #783 sloeg alleen de tekst "…te klein voor dit contract" over. Echte minimum-orderfouten komen uit `ContractRules.market_quantity` als "Deze gedeeltelijke sluiting past niet binnen de Aster contractregels: Order ligt onder de minimale Aster-hoeveelheid / -orderwaarde / Hoeveelheid en marktprijs moeten positief zijn" en stopten de héle reeks. Aangetoond met de echte route (TINY-positie).
2. **Stale lees-venster in de route (concurrency).** De route las posities + hoeveelheid vóór de account-lease. Draaide de Auto Hedge-worker daartussen (hedge-grootte wijzigt), dan werd er toch een order verstuurd op de oude hoeveelheid, de na-controle gaf 502 en het paar kreeg `MANUAL_RELEASE_UNCERTAIN`. Mutatietest bewijst dit op de oude bron.
3. **Worker leest vóór lease (concurrency).** `_run_uid` nam de lease pas ná `_prepare_lifecycle`; een worker die vóór de close begon kon na het vrijgeven van de lease handelen op een pre-close snapshot (her-hedge na handmatige close).
4. Al aanwezig en correct (niet gewijzigd): idempotency per klik (`asterManualCloseIntents`, tweede identieke sleutel → 409), één POST per order en geen herhaling bij onbekende uitkomst (502 "er wordt niet opnieuw besteld"), lease over freeze+order voor Auto Hedge-benen, freeze (`MANUAL_RELEASE_PENDING`) vóór de order, `expected_quantity`-controle, fail-closed lockreader, geen retry in proxy; `authenticatedRequest` herhaalt alleen 401 met dezelfde body (zelfde idempotency-sleutel).

## Minimale codewijzigingen (3 plekken)
- `web/components/aster-recent-trades.tsx`: (a) skip ook de exacte ContractRules-minimumfouten; (b) skip een pre-order weigering "zou Auto Hedge-dekking onder de gereserveerde … brengen" (geen order, geen statuswijziging), geteld en getoond; (c) bij "Auto Hedge verwerkt momenteel dezelfde accountstatus" (pre-order) maximaal 3× opnieuw met **nieuwe** sleutel na 1,5 s, daarna stoppen; (d) bevestigingsdialoog toont het bestaande Auto Hedge-gevolg (Recovery, re-hedge UIT). UNKNOWN, netwerk-/proxyfout, HTTP 5xx, gewijzigde hoeveelheid en alle andere fouten stoppen de reeks, nooit een retry.
- `cloud_api/main.py` (+9 regels, alleen binnen het Auto Hedge-releasepad): na het verkrijgen van de lease posities opnieuw lezen en `expected_quantity` hervalideren (409 vóór freeze/order).
- `cloud_api/aster_position_loss_auto_hedge_extension.py`: lease-acquisitie verplaatst naar vóór `_client`/positielezing/`_prepare_lifecycle` (zelfde acquire/busy/release-logica, geen fences/renew, geen Recovery-/claimwijziging).
Geen nieuwe route, geen nieuwe guards, geen wijziging aan statusovergangen, thresholds, Recovery of andere Close-knoppen.

## Waarom bestaand handmatig gedrag behouden blijft
Elke SHORT gaat via dezelfde route met dezelfde body als de losse knop. Test: eindtoestand van een bulk-serie (pair → RECOVERY, rehedge UIT, LONG onaangeroerd) is gelijk aan individuele clicks in willekeurige volgorde. De route-wijziging doet alleen iets in een race (hervalidatie) en raakt de niet-Auto-Hedge-paden niet.

## Tests (alles offline)
| Suite | Resultaat | Type |
|---|---|---|
| `cloud_api/test_close_profits_2_0_integration.py` | **PASS 17/17** (met httpx-stub; SKIP zonder httpx) | Echte route/helpers/lease/lock-bron + **gemodelleerde** Firestore en Aster-ledger |
| `web/tests/aster-close-profits-integration.test.mjs` | **PASS 8/8** met `CP20_PYTHONPATH` (httpx-stub); **SKIP 8** in omgeving zonder httpx | Echte frontend-handlers + echte proxycode + echte route, gemodelleerde Aster/Firestore. 25 SHORTs × 25/50/75/100%, 5 Auto Hedge, UNKNOWN, respons verloren na uitvoering, herhaalde klik, wijzigende hoeveelheid, worker-probe tijdens elke order, strikt > $0,50 (0,50 uit, 0,51 erin), geen LONG-orders |
| `web/tests/aster-close-profits-scope.test.mjs` + PR `short-handler` | PASS 16/16 | Handler in vm, mocks |
| backend suite | 2007 pass / 21 fail / 73 importfouten = identiek aan PR-head (1990/21/73) + 17 nieuwe; Auto Hedge 19/19, lifecycle 7/7, owner gate 5/5 PASS | pre-existing FAIL/import errors door ontbrekende dependencies |
| web suite | 150/152 bestanden; 2 pre-existing FAIL (`extreme-spike-settings-route-execution`, `rendered-html`) | |
| Mutaties | route zonder hervalidatie → test faalt (502 + UNCERTAIN bewezen); frontend-regel oud → integratietest faalt | |
| Firestore-emulator, echte FastAPI, echte Auto Hedge-worker, echte Aster | **NOT RUN** | geen omgeving/geen orders |
Het worker-gedrag is bewezen via bronvolgorde (lease vóór lezen) en een lease-probe op elke order; de echte worker-loop is niet uitgevoerd.

## Niet bewezen / risico's
1. Geen echte infrastructuur (emulator/FastAPI/Aster): modellen zijn geen bewijs.
2. Plain (niet-Auto-Hedge) SHORTs nemen geen lease; een nieuw ontstaand Auto Hedge-paar op hetzelfde moment is niet uit te sluiten (zelfde als snel handmatig klikken).
3. Worker houdt de lease nu langer (lezen + lifecycle); close ziet vaker "bezig" → frontend herprobeert max. 3×; TTL 45 s zonder renew (ongewijzigd principe).
4. Positie-lag aan Aster-kant na accepteren (position_risk nog oud) kan in theorie een tweede handmatige klik toelaten; bestaande route-eigenschap.
5. Winst wordt door de bestaande route niet opnieuw getoetst (alleen hoeveelheid); de > $0,50-drempel geldt bij preview. Aanvullende backend-herbeoordeling is niet toegevoegd (buiten scope).
6. De skip op "Auto Hedge-dekking" is praktisch zeldzaam (paar wordt vóór die controle bevroren) maar veilig: pre-order.
7. Security buiten scope: publieke repo met `gha-creds-*.json` (WIF-config, geen privésleutel).

## GO / NO-GO
Technische review: **GO**. Merge: **NO-GO** tot emulator/FastAPI-run in geschikte omgeving. Productie: **NO-GO** (bewijs ontbreekt: echte Firestore/Aster-integratie, echte workerrun). Build 601 en productie onaangetast; geen deploy, geen workflow gestart.

## Reproduceren
`cd cloud_api && python3 -m unittest test_close_profits_2_0_integration` · `cd web && CP20_PYTHONPATH=<dir met httpx-stub> node --test tests/aster-close-profits-integration.test.mjs tests/aster-close-profits-scope.test.mjs tests/aster-close-profits-short-handler.test.mjs`
