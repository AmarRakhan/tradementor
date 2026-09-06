# P0 KRITIEKE PRODUCTIE-OPDRACHT — DCA execution bug bij handmatig geselecteerde paren + correcte chart-levels + break-even

## Bindend uitgangspunt
Werk in de bestaande Crypto Bot 2026 / Aster webapp. De huidige live productieversie is **Webapp versie 46 — build 263**. Dit is het enige geldige uitgangspunt. Werk niet vanaf een oudere branch, build, testversie of losse featurebranch. Controleer vóór wijziging aantoonbaar dat de codebasis overeenkomt met v46 build 263.

## Absolute prioriteit
Laat alle overige niet-kritieke werkzaamheden tijdelijk liggen. De primaire storing is een echte trading execution bug: **bij handmatig geselecteerde paren worden DCA's niet daadwerkelijk uitgevoerd wanneer het DCA-niveau wordt bereikt of gepasseerd.** De foutieve DCA-lijn is waarschijnlijk slechts een symptoom. Trading execution eerst; visualisatie daarna.

## Huidige strategiecontext — bindend
Gebruik uitsluitend de huidige werking van v46 build 263. LONG en SHORT werken volledig onafhankelijk van elkaar: geen gezamenlijke hedge-cycle, ieder eigen positie, gemiddelde entry, DCA-logica, take profit en break-even. Beide sides mogen afzonderlijk DCA'en en TP halen. **Voeg geen oude hedge-logica opnieuw toe.**

## Actuele bug
Bij automatisch geselecteerde coins werkt DCA volgens waarneming wel. Bij handmatig geselecteerde trades niet. Concreet: positie open, volgende DCA zichtbaar, marktprijs bereikt/passeert trigger, maar er komt geen echte DCA-order/fill, positieomvang stijgt niet, DCA-count stijgt niet en oude DCA-state/chart-lijn blijft staan alsof de trigger nog toekomstig is.

## Onderzoek manual versus auto execution path
Vergelijk exact dezelfde flow voor automatisch en handmatig gekozen pairs. Controleer minimaal:
- pair normalization en symbol mapping;
- manual-selection flag en strategy enrollment;
- scheduler/scanner inclusion;
- active position/cycle lookup;
- LONG/SHORT ownership, side/position/pair/cycle keys;
- DCA count/limit, next DCA price, last confirmed DCA fill;
- trigger registration/evaluation en server-trigger state;
- pending-order detectie, duplicate protection, idempotency, locks/cooldowns;
- pair eligibility/manual-pair filtering;
- exchange submit, precision/step size, min notional, leverage/margin validation;
- exchange response, rejects, partial/confirmed fills;
- persistence, reconciliation en restart recovery;
- frontend/backend payload mapping, cache/stale state en chart overlay source.

Zoek expliciet naar een pad waarbij een handmatig geselecteerd pair wel correct wordt geopend maar daarna niet meer door dezelfde DCA-engine wordt meegenomen als automatisch geselecteerde pairs. Los de root cause structureel op.

## Geen cosmetische workaround
Niet acceptabel: alleen lijn verplaatsen/verbergen of frontend-state overschrijven. Vereist: server detecteert geldige trigger, order wordt aangemaakt en naar Aster/exchange gestuurd, fill wordt verwerkt, DCA-count en gemiddelde positie worden correct gereconcilieerd, nieuwe volgende DCA wordt berekend en de chart ontvangt daarna de echte state.

## Hard acceptatiepad DCA
Voor een handmatig geselecteerd pair moet aantoonbaar werken:
1. positie bestaat;
2. juiste side gekoppeld;
3. volgende DCA correct berekend;
4. markt bereikt/passeert trigger;
5. server detecteert trigger;
6. trigger wordt niet foutief gefilterd;
7. DCA-order aangemaakt;
8. order naar exchange;
9. exchange accepteert;
10. fill bevestigd;
11. positieomvang verandert;
12. gemiddelde entry bijgewerkt;
13. DCA-count stijgt;
14. fill opgeslagen;
15. oude trigger gesloten;
16. nieuwe volgende DCA berekend;
17. backend payload correct;
18. oude chart-lijn verwijderd;
19. nieuwe geldige lijn getoond.

## Geen blinde catch-up
Als actieve posities al één of meerdere niveaus hebben gepasseerd: **niet blind alle gemiste DCA's uitvoeren.** Eerst actuele exchange-positie, botstate, DCA-count, confirmed fills en pending/rejected orders uitlezen en reconciliëren. Daarna slechts de veilige volgende geldige actie bepalen. Voorkom dubbele orders, replay, meerdere catch-up orders tegelijk, verkeerde average entry/count en exchange/bot inconsistentie.

## Handmatige fills
Behoud bestaande manual-fill adoption/reconciliation. Als gebruiker op Aster/exchange handmatig bijkoopt, mag de bot geen dubbele exposure creëren. Eerst state correct adopteren/reconciliëren voordat automatische DCA verdergaat.

## Correcte DCA chart-state
Na execution fix moet chart altijd echte server/exchange-state volgen. Voor LONG en SHORT: next DCA is de echte eerstvolgende geldige DCA; geen gepasseerde/stale trigger; na fill direct nieuwe DCA; refresh/reconnect/backend restart/reconciliation leveren dezelfde correcte waarde.

## Nieuwe break-evenlijnen
Voeg daarna twee zelfstandige lijnen toe:
- **LONG BE** voor de actuele LONG;
- **SHORT BE** voor de actuele SHORT.
LONG en SHORT zijn volledig onafhankelijk en moeten visueel/functioneel symmetrisch worden behandeld. Gebruik actuele gemiddelde entry/positiegegevens; fees/funding alleen als de brondata betrouwbaar en consistent beschikbaar is. Geen schijnprecisie.

## Chart-levels per side
LONG: LONG TP, LONG BE, volgende LONG DCA.
SHORT: SHORT TP, SHORT BE, volgende SHORT DCA.
Huidige koers duidelijk zichtbaar. Voeg compacte afstanden toe waar passend, o.a. Naar LONG BE, Naar SHORT BE, Naar LONG TP, Naar SHORT TP, Naar LONG DCA, Naar SHORT DCA.

## Visuele referentie
Gebruik als visuele implementatierichting:
https://chatgpt.com/s/m_6a9de68c439481919d79980fd04d5885
Behoud de bestaande Crypto Bot 2026 look-and-feel; geen volledige redesign.

## Strategie niet wijzigen
Niet inhoudelijk wijzigen tenzij strikt noodzakelijk voor deze root-cause fix: entrylogica, TP-logica, DCA-afstand/bedragen, leverage, scanner, auto/manual pair-selectie buiten de bug, order sizing, active-position regels, restartlogica, ownership, exchange safety, budgetchecks, pair overrides, Portfolio TP en overige instellingen.

## Verplichte tests
A. Auto LONG: trigger -> echte order/fill -> count +1 -> nieuwe next DCA -> chart correct.
B. Auto SHORT: idem.
C. Manual LONG: cruciale regressie; echte order/fill/count/next DCA/chart.
D. Manual SHORT: idem.
E. Manual LONG + SHORT zelfde pair: onafhankelijke DCA/BE/TP, geen hedge-afhankelijkheid.
F. Browser refresh: DCA/BE/TP/count correct.
G. App opnieuw openen: zelfde state.
H. Backend restart: geen stateverlies.
I. Reconciliation: exchange waarheid herstelt lokaal.
J. Partial fill: geen dubbele DCA.
K. Rejected order: count niet onterecht verhogen.
L. Manual fill: correct adopteren/herstellen.

## Bestaande actieve posities
Controleer ook reeds actieve handmatig geselecteerde positions die mogelijk geraakt zijn. Per relevante positie: exchange qty, average entry, DCA-count, confirmed/pending/rejected orders, next DCA, actuele prijs, botstate en exchange state. Herstel alleen via veilige reconciliation; geen blind catch-up.

## Logging
Log waar nodig: pair, side, manual/auto mode, current price, next DCA, trigger true/false, block reason, position found, order requested/ID, exchange response, fill ID, DCA-count voor/na, nieuwe next DCA. Geen secrets loggen.

## Acceptatiecriteria
Gereed pas als aantoonbaar geldt:
- v46 build263 was de basis;
- manual pairs DCA'en weer echt;
- auto pairs blijven correct;
- LONG/SHORT DCA werken;
- echte exchange orders/fills correct verwerkt;
- count klopt, geen doubles/gemiste/stale triggers;
- LONG BE en SHORT BE correct;
- LONG TP en SHORT TP correct;
- LONG/SHORT blijven onafhankelijk;
- refresh/reconnect/restart/reconciliation correct;
- strategie verder intact;
- mobiele chart sluit aan op referentie;
- productie gedeployed en live gecontroleerd.

## Oplevering
Niet stoppen bij analyse, lokale fix, commit, PR, testomgeving of staging. Werk door tot live productie en rapporteer: exacte root cause; waarom manual pairs geraakt werden; aangepaste bestanden/modules; gerepareerde execution path; duplicate/stale preventie; LONG BE/SHORT BE berekening; uitgevoerde tests/resultaten; nieuwe versie/build; deploymentstatus; live bevestiging; controle actieve manual pairs.

**SLOT: Trading execution eerst. Visualisatie daarna. Een correcte grafiek zonder werkende DCA-order is géén oplossing. P0: doorwerken tot live productie.**
