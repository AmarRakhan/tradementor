# Aster Strategy 2 — Build- en vrijgavestatus

## Veiligheidsstatus

Strategy 2 is in aanbouw en **niet LIVE READY**. De live execution adapter blijft vergrendeld. Bestaande Aster-posities worden niet geclaimd of gewijzigd.

## Reeds gebouwd

- Afzonderlijke LONG- en SHORT-harveststate.
- Fixed, progressive en custom DCA-model met afzonderlijke LONG/SHORT-instellingen.
- Weighted entry op werkelijk gevulde hoeveelheid.
- Netto TP na vastgelegde fees/funding.
- Dynamische rollen HARVEST, HARVEST_PROTECTION en PROTECTION.
- Full TP, partial TP en protection-retentie op basis van portfolio-impact.
- NORMAL, CAUTION, DEFENSIVE en EMERGENCY.
- Strategy Budget, max DCA en UNKNOWN-state blokkades.
- Cashflow-adjusted return en High-Water Mark.
- Configversies en history-opslag.
- Strategy Maker-wizard en Paper Start.
- Deterministische bull-, bear-, sideways-, crash-, pump- en reversalsimulaties.
- Officiële Aster V3-uitlezing van orderhistorie, werkelijke/partial fills en funding/fees.
- Read-only live-readinesspoort met zichtbare controles in Strategy Maker.

## Nog vereist vóór livevrijgave

- Ownership-migratie voor reeds bestaande posities zonder twijfelgevallen.
- Restart round-trip met alle states en open orders.
- Contractcapabilitymatrix voor leverage en margin mode.
- Close All preview met kosten/protectionimpact.
- Minimale echte open/fill/close-canary met afzonderlijke persoonlijke toestemming.

## Laatste geautomatiseerde controle

- Totale backendtests: 207 geslaagd, 0 mislukt.
- Strategy-2 marktflows: bull, bear, sideways, crash, pump en reversal geslaagd.
- Failure checks: onbetrouwbare exchange-state, onbekende orderstatus en onzekere ownership blokkeren nieuw risico.
- Partial fill: alleen werkelijk gevulde hoeveelheid wijzigt weighted entry; hetzelfde fill-ID is idempotent.
- Cashflows: deposit telt niet als winst en withdrawal niet als verlies.
- Webproductiebuild: geslaagd.

Dit rapport bewijst nog geen echte Aster-orderflow. Daarom blijft `liveReady=false` en weigert de live-startendpoint Strategy 2 met een duidelijke reden.
