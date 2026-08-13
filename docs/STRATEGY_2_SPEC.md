# TradeMentor Strategie 2 — specificatie

## Status

De functionele specificatie is gereed. Strategie 2 blijft uitgeschakeld en technisch vergrendeld totdat uitvoering, simulatie en veiligheidstests aantoonbaar gereed zijn. Dit document activeert geen handel en voert geen order uit.

## Mandaat en prioriteit

Strategie 2 mag zelfstandig instrument, LONG/SHORT-richting, instap, uitstap, positieomvang, eventuele hedge en hefboom bepalen om de portfoliowaarde te laten groeien. Kapitaalbehoud is een harde prioriteit. Een kans wordt overgeslagen zodra de liquidatie-, uitvoerings- of dataveiligheid niet overtuigend kan worden aangetoond.

De gebruiker geeft na selectie geen handmatige inhoudelijke input voor tradebeslissingen. Alleen de keuze van de ene actieve strategie is handmatig. Strategieën zijn exclusief: wanneer Strategie 2 geselecteerd is, mogen Strategie 1, 3, 4, 5 en 6 geen signalen of acties leveren. Zolang de Strategie-2-uitvoering niet gevalideerd is, resulteert selectie veilig in nul signalen en nul orders; er is geen terugval naar een andere strategie.

## Conservatieve ontwerpgrenzen

- Hefboom: standaard 1×, risicogestuurd en nooit boven 3×.
- Risico bij harde stop: maximaal 0,5% van de actuele portfoliowaarde per positie.
- Notionele positieomvang: maximaal 10% van de portfoliowaarde per positie.
- Totale bruto blootstelling: maximaal 50%.
- Totale netto richtingsblootstelling: maximaal 25%.
- Dagelijkse drawdown/circuit-breaker: 2% op gerealiseerd plus ongerealiseerd resultaat.
- Gecorreleerd cluster: maximaal drie posities en maximaal 20% bruto blootstelling.
- Een geplande stop moet ruim vóór de liquidatiezone liggen. Kan dat niet, dan volgt geen trade.

Deze grenzen zijn startwaarden voor validatie, geen uitnodiging om de limieten op te zoeken. Volatiliteit, liquiditeit, correlatie, funding en accountdruk kunnen alle limieten alleen verder verlagen.

## Verplichte exits en fail-safe

Voor uitvoering bestaan een harde stop, winst-/afbouwplan, tijdslimiet en thesis-invalidatie. Een positie wordt niet onbeperkt aangehouden. Ontbrekende data, afwijkende prijzen, orderonzekerheid, cloudproblemen of onbevestigde stopbescherming blokkeren nieuw risico. Bij een onbeveiligde uitgevoerde positie volgt veilige afbouw en pauzering.

## Hedge en richting

Een hedge is optioneel en alleen toegestaan wanneer het netto portefeuillerisico aantoonbaar daalt. Een hedge mag geen verborgen hefboom of schijnveiligheid toevoegen. Een gelijktijdige LONG/SHORT-balans is een mogelijke techniek, maar geen verplichte strategie-eis.

## Vereiste validatie vóór activering

1. Unit- en integratietests voor iedere beschermrail.
2. Backtests inclusief fees, funding, slippage en ontbrekende data.
3. Stresstests voor gaps, extreme volatiliteit, correlatiesprongen en cloud/orderstoringen.
4. Paper trading met volledige auditlogboeken.
5. Controle dat limieten server-side worden afgedwongen en niet alleen in de appweergave.
6. Expliciete vrijgave voordat Strategy 2 in de scanner kan worden aangezet.

## Meet- en leerkring

Strategie 2 is resultaatgericht en mikt op betekenisvolle risico-gecorrigeerde groei, niet op een geforceerd minimaal dagelijks groeipercentage. Vooraf gedefinieerde maatstaven omvatten netto gerealiseerd rendement, fees, funding, maximale drawdown, liquidatiedruk, stopafstand, looptijd, resultaatvolatiliteit en groei per tijdseenheid.

Iedere gesloten trade en iedere vaste evaluatieperiode wordt beoordeeld. Parameters mogen alleen gecontroleerd veranderen wanneer voldoende bewijs uit gescheiden backtest- en paper-tradingdata dezelfde verbetering ondersteunt. Een korte winst- of verliesreeks is nooit voldoende. Liquidatie-, drawdown- en blootstellingslimieten mogen door de leerkring niet worden versoepeld. Historische uitkomsten zijn evaluatiebewijs, geen garantie.

## Attributie en uitbetaling

Iedere door TradeMentor geselecteerde trade krijgt vóór uitvoering precies één onveranderlijke `strategyId` en strategienaam. Bij sluiten worden gerealiseerde PNL, fees en waar beschikbaar funding onder dezelfde strategie opgeslagen. Externe Hyperliquid-posities krijgen expliciet de bron `external_hyperliquid` en worden niet ten onrechte aan Strategie 1 of 2 toegeschreven.

De historische vergelijking rapporteert per strategie gesloten trades, netto resultaat na vastgelegde kosten, winratio en vastgelegde risicogrens. De rapportage beschrijft historische prestaties en mag niet als winstbelofte worden gepresenteerd.

## Beoordelingsmaatstaven

Vergelijk Strategie 2 eerlijk met andere strategieën op netto rendement, maximale drawdown, liquidatiedruk, resultaatvolatiliteit, tijd tot resultaat en portefeuillegroei per tijdseenheid. Een trade telt niet als veilig succes wanneer een beschermrail tijdens de looptijd faalde.
