# Money Grabber – technisch stagingrapport

Datum: 19 augustus 2026

## Inventarisatie en oorzaak

De bestaande Portfolio Protection bepaalt algemene risicomodi op basis van
drawdown en margin. Zij blokkeert in noodsituaties nieuwe exposure, maar heeft
geen duurzame per-symbool state machine voor een automatisch tegengesteld paar
en geen portfolioronde met netto sluitdoel. Money Grabber is daarom als aparte
Strategy-2-configuratie, ronde-state en paar-state gebouwd; `protectionEnabled`
is niet hergebruikt.

## Bron en commits

- Doelbranch: `amar-crypto-bot-2026-cloud`
- Featurebranch: `codex/money-grabber-portfolio-rounds`
- Basiscommit: `e948f07a620e41ece7838c94ca36ff258dff0c46`
- Lokale geteste hoofdcommit: `bae956154200fbe5bae50390f8362fb4526427d2`
- Testsitecommit: `76d445e8a9bbf9b0d4bcb9673ec0d198e630de32`
- PR/mergecommit: nog niet beschikbaar; GitHub-publicatiepoort geblokkeerd

## Belangrijkste modules

- `cloud_api/money_grabber.py`: netto waardebewijs, ronde- en paarregels.
- `cloud_api/money_grabber_runtime.py`: accountplanner en orderlimiet 15.
- `cloud_api/money_grabber_execution.py`: Hedge Mode-ordercontracten.
- `cloud_api/money_grabber_state.py`: herstel na restart en partial fills.
- `cloud_api/money_grabber_intents.py`: duurzame idempotency ledger.
- `cloud_api/main.py`: configuratie, preview, start-round, shadow en
  scheduler-shadowintegratie.
- `web/components/aster-strategy2-maker.tsx`: wizard en rondestatus.
- `web/lib/secure-strategy2-live.ts`: afgeschermde proxy-allowlist.
- `web/app/api/exchanges/aster/strategy2/money-grabber/**`: concrete GET/POST
  browserroutes.

## Veiligheid

- Money Grabber is standaard uit.
- Alleen Strategy 2 leest de Money Grabber-configuratie.
- Activatie vereist een frisse preview en expliciete fingerprintbevestiging.
- Schedulerintegratie is read-only shadow en bewaart
  `moneyGrabberExecutionEnabled=false`.
- Shadowclients zijn `live_authorized=False`.
- Geen echte Money Grabber-testorders uitgevoerd.
- Publieke TradeMentor-omgeving niet gewijzigd.

## Testbewijs

- Volledige backend-suite: 633 geslaagd.
- Gerichte Strategy-2/Money Grabber-regressie: 230 geslaagd.
- Volledige websuite en productieachtige build: 101 geslaagd.
- Testcategorieën: configuratie-isolatie, LONG/SHORT-DCA-isolatie,
  rondeberekening, partial/full protection, gezamenlijke paarsluiting,
  rondeafsluiting, idempotentie, restart/recovery, property-invarianten,
  25-stappen simulatie en webroutecontracten.
- Simulatie en shadow verstuurden nul exchange-orders.

## Testpublicatie

- Testwebapp: https://tradementor-staging-2026.amar-rakhan.chatgpt.site
- Sites-versie: 18
- Deployment: `appgdep_6a857e4e998c819182b89f5bba6c6715`
- Status: succeeded
- Testbackend-revision/run: nog niet beschikbaar

## Openstaande poorten

1. Push featurecommit en maak PR naar de vaste doelbranch.
2. Publiceer exact die commit naar de geïsoleerde Strategy-2-testbackend.
3. Controleer health, IAM, environment flags, schedulerstaat en OpenAPI-routes.
4. Voer read-only accountshadow en visuele Fold-controle uit.
5. Bouw pas daarna de echte Money Grabber-uitvoeringskoppeling vrij; momenteel
   blijft die bewust centraal uit.
6. Publieke promotie is niet toegestaan voordat al het bovenstaande groen is.

## Rollback

De testsite kan worden teruggezet van versie 18 naar de vorige opgeslagen
Sites-versie 17. Backendrollback is nog niet van toepassing omdat de nieuwe
backendcommit niet is gepubliceerd. Money Grabber blijft bovendien standaard
uit en de schedulerroute is shadow-only.
