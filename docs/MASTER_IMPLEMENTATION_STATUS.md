# TradeMentor masteropdracht — implementatiestatus

Bijgewerkt: 2026-08-08

Dit bestand is de controlelijst voor de definitieve masteropdracht. Een onderdeel
is pas **gereed** wanneer broncode, tests, persistente state, appkoppeling en de
bijbehorende releasegate aantoonbaar zijn geslaagd.

## Statuslegenda

- **Gereed:** lokaal geïmplementeerd en getest.
- **In uitvoering:** fundament bestaat, maar de volledige app/cloudkoppeling of gate ontbreekt nog.
- **Geblokkeerd voor release:** mag nog niet in productie worden geactiveerd.

## 1. Bestaande werking beschermen

- **Gereed:** werkmap, builds, terugvalversie en dirty worktree vastgelegd.
- **Gereed:** MEXC V3 stopguard voorkomt lokaal dat gestopte automatisering een handmatig gesloten side heropent.
- **In uitvoering:** geïsoleerde cloudintegratietest en gecontroleerde productiepublicatie van deze MEXC-fix.
- **Gereed:** 45 Android-tests en 122 cloudtests slagen lokaal.

## 2. Navigatie

- **Gereed in bron:** exact MEXC, HYPERLIQUID, ASTER en WALLET.
- **Gereed in bron:** Strategy is bereikbaar onder Hyperliquid.
- **In uitvoering:** officiële logo-assets, volledige schermkoppeling en visuele toestelcontrole.
- **Geblokkeerd voor release:** geen APK voordat de toestelcontrole en regressiegates slagen.

## 3. Hyperliquid live migratie

- **Gereed:** exchange-authoritatief snapshotmodel met stabiele digest.
- **Gereed:** ontbrekende exchange-read pauzeert; mismatch levert `SYNC_REQUIRED` op.
- **Gereed:** onbekende/tegenstrijdige enabled-status blijft veilig UIT.
- **In uitvoering:** geauthenticeerde pre-installatiesnapshot, Firestore round-trip en fill/DCA-reconstructie aansluiten.

## 4. Aster Futures

- **Gereed:** V3-contractmodel volgens officiële Aster-documentatie.
- **Gereed:** standaard OFF/paper; expliciete LONG/SHORT; Hedge Mode- en riskgate.
- **Gereed:** exchangefilters, minimale orderwaarde, quantity-step en leveragebrackets.
- **Gereed:** multi-pair Long/Short-state en out-of-order streambeveiliging.
- **Gereed:** HTTP 503 wordt als onzekere orderstatus behandeld en niet blind herhaald.
- **In uitvoering:** veilige EIP-712-authadapter, Secret Manager, REST/WebSocket-runtime en persistente fillreconstructie.
- **Geblokkeerd voor release:** geen live Aster-orders of credentials totdat testnet/recovery/riskgates compleet zijn.

## 5. Centrale Portfolio Risk Manager

- **Gereed:** totale equity, available, gross/net exposure en marginratio over exchanges.
- **Gereed:** noodreserve, liquidatieafstand, gross-exposure-, concentratie- en drawdownlimieten.
- **Gereed:** stale of onleesbare exchange-data blokkeert nieuwe exposure.
- **In uitvoering:** actuele exchange-snapshots en gebruikers-/strategiebeleid aansluiten.

## 6. Centrale Order Coordinator

- **Gereed:** unieke intentie, verlopen intentie, replay, uncertain en rejectgedrag.
- **Gereed:** OPEN/ADD/HEDGE vereist alle gates; CLOSE/CANCEL blijft beschermend beschikbaar.
- **In uitvoering:** Firestore-transacties/locks en adapters voor alle drie exchanges aansluiten.

## 7. Aster USDT Market Selector

- **Gereed:** ieder positief geheel Top-N-getal blijft exact behouden.
- **Gereed:** alleen actieve Aster USDT-perpetualcontracten met complete ordermetadata blijven over.
- **Gereed:** rangschikking gebruikt Aster 24-uurs quotevolume en liquiditeit; stale data blokkeert alleen nieuwe instappen.

## 8. Wallet

- **Gereed:** pure aggregatie zonder unrealized PnL dubbel te tellen.
- **Gereed:** ontbrekende of stale exchange wordt zichtbaar als voorlopig totaal.
- **In uitvoering:** app-UI en echte MEXC/Hyperliquid/Aster snapshots aansluiten.

## 9. Startup en herstel

- **Gereed:** per-exchange gates, betrouwbare enabled-restore en begrensde reconnect-backoff.
- **Gereed:** nieuwe Aster-installatie blijft UIT; één defecte exchange blokkeert geen gereedstaande andere exchange.
- **In uitvoering:** Cloud Run startup, WebSocket lifecycle, 24-uurs reconnect en chaos/restarttests.

## Releasebesluit

De masteropdracht is **nog niet releaseklaar**. Er is bewust geen nieuwe APK
gebouwd en niets naar de productiecloud gepubliceerd. De huidige nieuwe code is
een lokaal getest veiligheidsfundament; echte adapters en end-to-end gates
moeten nog worden afgerond.
