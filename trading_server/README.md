# TradeMentor lokale handelsserver

Deze server gebruikt de officiële Hyperliquid Python SDK. Echte orders zijn standaard vergrendeld.

1. Installeer eenmalig de pakketten uit `requirements.txt`.
2. Start `start_server.ps1`.
3. Vul het hoofdwalletadres en uitsluitend de aparte Hyperliquid API-walletsleutel in.
4. Controleer eerst `/health` en `/preflight`.

Een echte testorder is alleen mogelijk wanneer de server bewust wordt gestart met
`TRADEMENTOR_ALLOW_ONE_TEST_ORDER=true` en de eenmalige bevestiging wordt meegestuurd.
Na één poging vergrendelt de server opnieuw. Automatisch handelen is nog niet actief.
