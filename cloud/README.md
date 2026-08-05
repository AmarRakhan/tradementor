# TradeMentor cloudvoorbereiding

Deze map bevat de veilige multi-userbasis. Google Cloud-project
`tradementor-production`, Firebase Authentication en de Firestore-database zijn op
3 augustus 2026 aangemaakt. De eerste Cloud Run API is actief op
`https://tradementor-api-604335232956.europe-west4.run.app`. De huidige
`trading_server` blijft de lokale single-user productieomgeving totdat walletdata,
scannerprocessen en orderuitvoering afzonderlijk in de cloud zijn getest.

## Benodigde openbare waarden

- Google Cloud project-ID
- Cloud Run regio (aanbevolen: `europe-west4`)
- uiteindelijke Cloud Run HTTPS-URL
- Firebase Android-configuratie `app/google-services.json`

Nooit in de repository of chat plaatsen: Google-wachtwoorden, betaalgegevens,
Firebase service-accountbestanden, MetaMask seed phrases of wallet-private keys.

## Beoogde diensten

- Firebase Authentication: persoonlijke account-ID (`uid`)
- Firestore: instellingen, tradehistorie, apparaten en abonnementsstatus per `uid`
- Cloud Run: geauthenticeerde API en orderorchestratie
- Secret Manager + KMS: versleutelde gebruikers-agentwallets
- Pub/Sub / Cloud Tasks: idempotente scan- en ordertaken
- Google Play Billing: later; de server verleent rechten pas na server-side verificatie

## Volgorde

1. Google Cloud-project en Firebase zijn aangemaakt; facturering en een maandbudget van €10 met waarschuwingen op 50%, 80% en 100% zijn actief.
2. Firebase is gekoppeld en `com.tradementor.app` is geregistreerd.
3. `google-services.json` staat gecontroleerd in `app/`; Firebase SDK-build is geslaagd.
4. `/health` en `/v1/me/bootstrap` zijn als `tradementor-api` naar Cloud Run in `europe-west4` gepubliceerd en getest; orders staan uit.
5. Test twee accounts en twee telefoons op volledige datascheiding.
6. Migreer scannerstatus en tradehistorie.
7. Migreer pas daarna orderuitvoering; voer eerst Testnet- en idempotentietests uit.

## Cloud Run-revisies

- Revisie 6 (`tradementor-api-00006-75v`, 3 augustus 2026): dubbele
  bronblokken verwijderd en alle twaalf API-routes op uniciteit gecontroleerd.
  De productie-healthcheck, Firebase-afgeschermde Live Positions-route en
  persoonlijke agentwalletstatus zijn gecontroleerd. Echte orders blijven
  bewust vergrendeld (`ordersEnabled: false`).
- Revisie 7 (`tradementor-api-00007-nt9`, 3 augustus 2026): Firebase-beveiligde
  tweerichtingssynchronisatie toegevoegd voor scannerstatus, persoonlijke
  handelsinstellingen en maximaal 2.500 trades per gebruiker. Stabiele trade-id's
  maken herhaalde uploads idempotent; orderroutes blijven vergrendeld.
- Revisie 8 (`tradementor-api-00008-4hc`, 3 augustus 2026): transactionele
  orderintenties met een unieke aanvraaglock én aparte pairlock. Dit bereidt
  veilige herhaalbare orderverwerking voor, maar voert nog geen orders uit.
- Revisie 9 (`tradementor-api-00009-98v`, 3 augustus 2026): orderloze
  cryptografische preflight. De agentwallet ondertekent en verifieert uitsluitend
  in Cloud Run met de sleutel uit Secret Manager; alleen het testresultaat wordt
  geretourneerd en `ordersEnabled` blijft false.
8. Activeer betalingen pas na Play Billing-serververificatie en juridische beoordeling.
