# Close Profits 2.0 — EINDRONDE: echte infrastructuur via GitHub Actions + productiedossier (21 okt 2026)

Branch `review/close-profits-2-0-minimal-20261021`. Productiecode t.o.v. PR #783-head f8cd2af: **3 bestanden** (`cloud_api/main.py`, `cloud_api/aster_position_loss_auto_hedge_extension.py`, `web/components/aster-recent-trades.tsx`). Rest = tests/harness/CI/docs. Niets gedeployed, niet gemerged, geen productie, geen live-orders, 2.1-branch onaangetast.

## Infrastructuur (echt, geïsoleerd, geen secrets)
GitHub Actions-workflow `.github/workflows/close-profits-2-0-integration.yml` (publieke repo, gratis): Firestore-emulator (firebase-tools 14.21.0, Java 21, project `close-profits-test-only`), echte FastAPI-app, echte gateway/`execute_leg_once`, echte worker-code `_run_uid`, Playwright-Chromium. Aster = HTTP-fake via httpx-transport (nooit het echte Aster; socketguard actief). Dit is **geen** test tegen echt Aster of productie-Firestore.

## Resultaten (laatste run, SHA a1171aa9)
| Onderdeel | Resultaat |
|---|---|
| Firestore-emulator (echte SDK/transacties/leases) | PASS 33/33 |
| Echte FastAPI + gateway e2e (25 SHORTs × 25/50/75/100 %, uitzonderingen, worker-races, simultane requests) | PASS 20/20 |
| Frontend → Next-proxy-pad → echte FastAPI → emulator | PASS 11/11 |
| Echte Chromium UI-check (knop, dialoog, percentages, falen, overflow) | PASS 12/12 |
| Volledige web-suite | PASS (exit 0) |
| Next production build | PASS |
| Backend regressie | 1 FAIL, **bestaand**: `test_every_production_aster_close_is_forced_through_shared_executor` faalt ook op PR-head en productiebasis |
| TypeScript | 39 fouten, **identiek op alle refs** (bestaand); geen nieuwe |
| Baselines (PR-head, productiebasis) | draaien groen op dezelfde workflow |

## Gemeten, NIET opgelost (KNOWN_RESIDUAL)
1. Winst kan in het ms-venster tussen verse controle en order dalen; de bestaande route controleert geen winst.
2. Gewone SHORT zonder tegenleg: twee gelijktijdige individuele closes → 2 orders mogelijk (bestaand; groene knop stuurt nooit twee tegelijk).
3. Handmatig opnieuw klikken met nieuwe sleutel tijdens vertraagde Aster-positiereflectie kan een 2e MARKET plaatsen (bestaand; individuele route ongewijzigd).
4. Lease-TTL 45 s zonder verlenging: bij exchange-/Firestore-stilstand > 45 s kan een nieuw Auto Hedge-paar op HEDGED blijven (altijd nog precies 1 order).
5. Meer "account bezig" op hedged symbolen; extra GET per positie/retry.
6. Echt Aster en productiedata nooit getest (bewust).

## Release-lineage (beslissing eigenaar vereist)
Canonieke branch `amar-crypto-bot-2026-cloud` (0eb6a58) is voorouder van deze branch (290 voor, 0 achter). Mergen fast-forwardt ~267 SHORT-Recovery-integratiecommits + Close Profits en triggert web-autodeploy (`deploy-shared-v44-testapp.yml`, push op `web/**`; vereist app-version/release-history-wijziging). "Build 601" vs bestandsbuild 603 onverklaard. Aanbeveling: minimale productiebranch vanaf de daadwerkelijk live commit + cherry-pick van uitsluitend de 3 productiebestanden (patch: `CLOSE_PROFITS_2_0_PRODUCT_ONLY.patch`).

## Deploy (alleen na toestemming)
1. Bepaal live commit/build; maak `release/close-profits-2-0` daarvan; pas product-patch toe; bump app-version + release-history.
2. Draai de workflow opnieuw op die branch (alles groen behalve het bestaande backend-falen).
3. Backend: `deploy-cloud-production.yml` (handmatig). Web: push naar `amar-crypto-bot-2026-cloud` (auto) of `deploy-shared-v44-testapp.yml`.
4. Rook: knop zichtbaar; individuele Close werkt; géén echte bulk-run zonder bewuste gebruikersactie.
## Rollback
Web: vorige Cloud Run-revisie/commit heractiveren (revert van de 3-bestanden-commit). Backend: vorige revisie 100 % verkeer. Er is geen datamigratie; idempotency-docs `asterManualCloseIntents` blijven onschadelijk.

---

# Close Profits 2.0 — handoff, REVIEWRONDE 6 (bovenaan; ronde 1–5 hieronder ongewijzigd als historie)

Code-commit ronde 6: `013b470427e3dce01f09a5e804edd6b60087a41f`. Start ronde 6: `dd70d3fe2356e0f9d9aa5f18ecc49bf7502f1367`. Geen live-orders, geen deploy/Cloud Build/workflow, geen merge, 2.1-branch en build 601 onaangetast.

## R6.1 + R6.2 Frontend: fail-closed controle vóór ELKE POST-poging (fix, failing-first)
Aangetoond op de ronde-5-code (11 nieuwe handler-tests, 8 FAIL vóór de fix, 11 PASS erna): (a) ontbrak de positie in de verse snapshot terwijl `selected` haar nog bevatte, dan werd er gesloten; (b) de controle gebeurde één keer vóór de retry-lus, dus na de 1,5 s "account bezig"-wachttijd kon winst/hoeveelheid veranderd zijn. Nu draait `freshCheck()` vóór de eerste poging én vóór elke retry: snapshot moet `reliable === true` zijn met arrays; de SHORT moet **precies één keer** in de rijen staan; volle hoeveelheid ongewijzigd; `unrealizedPnl` leesbaar en strikt > 0,50; nog door de planner geselecteerd. Niet meer geselecteerd → overslaan zonder order; al het andere onduidelijke (ontbrekend, dubbel, onleesbaar, tegenstrijdig, netwerkfout) → reeks stopt vóór de order. UNKNOWN/5xx/afwijkende tekst wordt nooit herhaald; max. 3 retries blijft. Alleen frontend gewijzigd; de individuele route niet.

## R6.3 Lease-expiry bij trage orders (onderzoek, geen codewijziging)
Feiten uit de code: TTL 45 s, geen verlenging; Aster-HTTP `timeout=15 s` (per fase: connect/write/read apart, dus geen harde totaalgrens); onder de lease: positielezing → Firestore-stappen → één POST (`execute_leg_once`: nooit een tweede POST, één read-only query, NEW/PARTIALLY_FILLED = RuntimeError → 502 "niet opnieuw besteld") → positielezing. `_release…` geeft alleen vrij bij eigen token.
Bewezen (model + echte `execute_leg_once`): (1) lease verloopt tijdens een late respons (+60 s): de worker *kan* de lease daarna nemen, maar het paar staat dan op `MANUAL_RELEASE_PENDING` met re-hedge UIT en dat is volgens de workerbron geen ACTIVE/REHEDGEABLE-status; de release van de route wist de lease van de worker niet; precies één order; (2) verloopt de lease tijdens de trage herlezing onder de lease, dan wordt een daarna aangemaakt paar alsnog bevroren (het paar wordt ná de exchange-lezing herlezen). Er is **geen pad naar een dubbele close-order door lease-expiry**: de enige code die een sluit-MARKET plaatst is de route zelf met deterministische order-id en idempotentie.
**Niet bewezen veilig (KNOWN_RESIDUAL-test):** gewone SHORT + tegenovergestelde leg + Auto Hedge aan, en de order/Firestore-stap duurt > 45 s: de worker maakt het paar ná de laatste paar-lezing aan → paar blijft `HEDGED` terwijl de SHORT wordt verkleind (nog steeds precies één order). Vereist een exchange-/Firestore-stilstand > 45 s. Niet opgelost: dat zou lease-vernieuwing of een lease-controle vóór de order in de bestaande route vragen. Productie blijft NO-GO.

## R6.4 Exchange-randgevallen (harness gebruikt nu de ECHTE `execute_leg_once`)
| Scenario | Resultaat (PASS) |
|---|---|
| gedeeltelijke fill (40 %) | 502 "niet opnieuw besteld", 1 order, paar `MANUAL_RELEASE_UNCERTAIN`, nieuwe sleutel/zelfde sleutel → 409, geen 2e order |
| vertraagde positiereflectie | 502, 1 order, zelfde sleutel geweigerd |
| timeout na acceptatie + read-only query vindt de order | 1 order, succes |
| timeout na acceptatie + query faalt | 502 UNKNOWN, 1 order, herhaling geweigerd |
| order-ack NEW, query laat FILLED zien | 1 order, succes |
| order-ack NEW blijft NEW | 502, 1 order |
| reject vóór uitvoering | 502, 0 orders, niets gewijzigd |
| reeks met UNKNOWN op 2e SHORT | stopt; 3e SHORT en alle LONG-legs onaangeroerd |
**Nieuw gevonden bestaand risico (KNOWN_RESIDUAL, gemeten):** zolang Aster's positie-endpoint nog de OUDE grootte toont, kan een mens op de **individuele** knop met een *nieuwe* sleutel opnieuw klikken en de route plaatst dan een tweede MARKET-sluiting (8 → 6 → 4). De groene knop doet dit niet (stopt op 502, geen herhaling); een nieuwe bulkactie direct na een gestopte reeks gebruikt echter dezelfde vertraagde data. Niet gewijzigd (route moet ongewijzigd blijven). Aanbeveling: na "Gestopt bij …" eerst Aster controleren; eventueel later een server-side "recente close"-vergrendeling per symbool.

## R6.5 Emulator-runner (statisch geverifieerd, niet uitgevoerd)
Gevonden en gecorrigeerd: (1) het script exporteerde `FIRESTORE_EMULATOR_HOST` globaal → de emulatortests zouden in stap 4 (pytest, geen emulator) draaien en falen; nu alleen binnen `emulators:exec` (Firebase zet de variabele zelf); (2) credentials/projecten worden `unset`; de emulatortests weigeren te draaien zonder localhost-host of met `GOOGLE_APPLICATION_CREDENTIALS`; (3) ronde-6-tests toegevoegd aan model- en emulatorstappen; (4) klokmodel: de geïnjecteerde `datetime` accepteert Firestore's eigen datetime-subklasse (`isinstance`-metaklasse, getest) — zonder dat had de lease op de emulator altijd vrij gelegen; (5) unieke `uid` per test, `demo`-project, Aster blijft ledger (geen netwerkcode in de harness; `httpx` alleen als import). `bash -n` en `py_compile` OK. Java 21 is aanwezig, maar `npm view firebase-tools` en `pip download google-cloud-firestore` worden door de proxy geweigerd (opnieuw één poging, niet omzeild).
Onderscheid: **modeltests** (in-memory Firestore-model, echte route/execute_leg_once), **Firestore-emulatortests** (zelfde scenario's, echte transacties; NOT RUN), **volledige applicatie-integratie** (echte FastAPI + Next + worker-loop; NOT RUN).

## R6.6 Tests (exact)
| Suite | PASS | FAIL | SKIP | NOT RUN |
|---|---|---|---|---|
| web `aster-close-profits-round6` (handler, fail-closed) | 11 | 0 | | |
| web alle close-profits + profitable (46; incl. 11 keten-tests met httpx-stub) | 46 | 0 | 0 | |
| backend `test_close_profits_2_0_round6` (model + echte execute_leg_once) | 15 | 0 | | |
| backend `test_close_profits_2_0_integration` | 24 | 0 | | |
| backend emulatortests | 0 | 0 | 33 | emulator |
| backend hele map vs ronde 5 | 2034 → 2062 pass (+15 nieuwe, +13 nieuwe emulator-SKIPs door runall als pass geteld), 21 FAIL en 73 importfouten onveranderd (pre-existing t.o.v. PR-head), alleen de twee nieuwe/uitgebreide bestanden verschillen | | | |
| web hele map | 151 van 153 bestanden; 2 FAIL pre-existing (`extreme-spike-settings-route-execution`, `rendered-html`) | | | |
| TypeScript-typecheck / Next-build | | | | NOT RUN |
| echte FastAPI, Firestore-emulator, worker-loop, Aster | | | | NOT RUN |

## R6.7 Resterende risico's
1. Geen run op echte infrastructuur. 2. Bestaand: tweede individuele klik met nieuwe sleutel tijdens vertraagde positiereflectie → tweede order (niet door de groene knop). 3. Pair-aanmaak na lease-expiry (> 45 s stilstand). 4. Winstvenster van enkele ms tussen verse controle en order. 5. Meer "account bezig" op hedged symbolen. 6. Eén extra GET per positie en per retry. 7. Publieke repo met `gha-creds-*.json`.

## R6.8 GO / NO-GO
Technische review: **GO**. Merge: **NO-GO** tot de emulatorrun groen is. Productie: **NO-GO** (geen echte infrastructuurrun; bewezen resterende risico's 2–4). Geen productietoestemming.

---
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
