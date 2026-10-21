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
