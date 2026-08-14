# Changelog

### [2.65-build234-test] - MEXC automatisering betrouwbaar hervatten
- De Auto Trade-knop onderscheidt nu actieve orderautomatisering van beschermende monitoring.
- Na `STOP AUTOMATISERING` blijft bestaande exposure veilig gemonitord, maar toont de app weer `START V3 LIVE` zodat een nieuwe cyclus expliciet kan worden hervat.
- Een aparte waarschuwing maakt zichtbaar wanneer alleen beschermingsmonitoring actief is en er geen nieuwe exposure wordt geopend.
- Dezelfde statuscorrectie geldt voor het oudere MEXC-dashboard en voor paperstart/-stop.
- Regressietests dekken actief, gestopt-met-bescherming, volledig gestopt en papertrading af; tijdens de tests worden geen echte orders geplaatst.
- Staging gebruikt voortaan expliciet de bestaande lokale TradeMentor-testkey, zodat een nieuwe testbuild als behoudende update kan worden geïnstalleerd zonder lokale appgegevens te wissen.
- Gebouwd op 8 augustus 2026 (UTC+2): `APK Releases/TradeMentor-Admin-v2.65-build234.apk` en `APK Releases/TradeMentor-Test-v2.65-build234.apk` vanuit de officiële staging-varianten.

### [2.64-build233-test] - MEXC Hedge DCA V3 / Test 3
- De bestaande MEXC-koppeling blijft behouden; alleen de strategielaag is vervangen door Hedge DCA V3.
- Long en Short hebben afzonderlijke cycles, weighted entries, take-profits, DCA-tellers en orderadministratie.
- De standaardpreset gebruikt BTC_USDT, Cross 200x, $70 notional per kant, 0,5% TP, maximaal 40 DCA-orders en een configureerbare DCA-afstand.
- De equity-noodrem annuleert pending DCA, vult de kleinere BTC-quantity aan tot vrijwel delta-neutraal en bevriest de verlieslatende cycle zonder klassieke stop-loss.
- Frozen en Rescue zijn afzonderlijke strategy-objecten; live Rescue blijft veilig op RESCUE_WAIT zolang MEXC geen aantoonbaar onafhankelijke positieomgeving levert.
- Het dashboard toont wallet, equity, available, unrealized PNL, Long/Short notional, net exposure, beide averages, TP's, DCA-tellers, noodremafstand en state.
- Basic en Advanced settings tonen alleen V3-instellingen; de standaardmodus blijft paper en de bot start niet automatisch na installatie.
- Scenario's A-L en extra validaties zijn geslaagd; Kotlin staging compile is geslaagd en er zijn geen echte orders geplaatst.
- Cloud Run-revisie `tradementor-api-00045-7b9` bedient 100% van het verkeer en antwoordt gezond; een bestaande actieve V2-cycle wordt niet stilzwijgend naar V3 gemigreerd.

### [2.63-build232-test] - volledige MEXC Adaptive DCA-cloudautomatisering
- MEXC BTC_USDT kan na expliciete live-start iedere minuut volledig vanuit Google Cloud worden bewaakt, ook wanneer de app of telefoon uit staat.
- De cloud stuurt eerste Long, zeven instelbare DCA-stappen, Dynamic Short Hedge, gefaseerde hedge-afbouw en netto take-profit aan vanuit de gekozen execution- en risk-timeframes.
- Long, DCA en Short Hedge gebruiken uitsluitend het vaste uitvoeringsprofiel Cross 200x; orderrichting en sluitvolume volgen de MEXC hedge-modecodes.
- Harde rails bewaken sessiedrawdown, marginbelasting, MEXC margin ratio, liquidatieafstand, vrije Cross-marge, onbekende open orders en onzekere orderstatus.
- Unieke order-ID's, een onveranderbaar orderjournaal, Cloud Scheduler-locks en exchange-reconciliatie voorkomen dubbel bestellen na time-outs of containerherstarts.
- Stoppen blokkeert nieuwe exposure; bestaande BTC-exposure blijft alleen voor take-profit en absolute veiligheid gemonitord tot alles vlak is.
- Appdashboard toont cloudfase, reden, DCA-teller, risk/recovery, netto sessieresultaat, fees en centrale automatiseringsstatus.
- Validatie: strategie- en gatewaytests, vijf deterministische marktscenario's, volledige staging-Kotlincompile en alle publicDebug-unit-tests geslaagd. Tijdens deze tests zijn geen echte orders geplaatst.
- De echte-data-droogtest op het gekoppelde MEXC-account gaf veilig `HOLD` en plaatste geen order; de definitieve minuutplanner antwoordde met HTTP 200.
- Productiecloud staat op revisie `tradementor-api-00044-rnx`; centrale automatisering is beschikbaar, maar iedere persoonlijke cyclus vereist nog steeds een expliciete live-start in de app.

### [2.62-build231-test] - vast MEXC Cross 200× uitvoeringsprofiel
- Long, DCA en de toekomstige Short Hedge gebruiken één niet-aanpasbaar profiel: Cross 200×.
- Oude lokaal opgeslagen hefboomwaarden worden bij laden en opslaan automatisch naar 200× genormaliseerd.
- De app weigert veilig een order wanneer de productiecloud niet expliciet Cross 200× bevestigt of MEXC minder dan 200× toestaat.
- De backtest gebruikt nu een Cross-marginmodel met gedeelde Futures-equity in plaats van de onjuiste Isolated-formule `1 ÷ leverage`.
- De liquidatiemonitor berekent Cross-posities tegen de gedeelde account-equity; Isolated-posities blijven tegen hun positiemarge rekenen.
- Validatie: alle Android-unit/backtests en 14 MEXC-cloudgatewaytests geslaagd; er zijn geen orders geplaatst.
- Productiecloud gepubliceerd als revisie `tradementor-api-00041-z6j`; health, verkeersroutering, bestaande omgevingsinstellingen en foutlogs gecontroleerd. Geen order geplaatst tijdens publicatie.

### [2.61-build230-test] - echte MEXC-livepositie en liquidatiemonitor
- Het Auto Trade-dashboard gebruikt nu de echte MEXC-posities voor richting, notional, gemiddelde instap, open PNL, hefboom en liquidatieprijs.
- De liquidatiemonitor toont de MEXC margin ratio in de juiste richting: 0% veilig en 100% liquidatie.
- De ratio wordt berekend met de actuele MEXC maintenance-margin- en liquidatiefee-tarieven en iedere vijf seconden vernieuwd.
- Backtests nemen voortaan leverage, marginbelasting en geschatte liquidatieafstand mee; 200x wordt bij een vereiste afstand van 8% terecht geblokkeerd.
- Een bestaande BTC-positie blokkeert een tweede canaryknop in de app.

### [2.60-build229-test] - gesimuleerde MEXC-vrijgave
- De volledige MEXC-canaryroute is vijfmaal gesimuleerd zonder echte orders; iedere ronde slaagde met 32/32 tests.
- De eerste echte canary blijft server-side begrensd op maximaal $8,50 totale BTC_USDT-positie en gebruikt altijd 1x hefboom.
- Een unieke externe order-ID voorkomt dubbel bestellen; na een onzekere respons wordt alleen gecontroleerd en nooit automatisch opnieuw besteld.
- De knop onderscheidt nu duidelijk `ACTIVEER LIVE` van de afzonderlijke bevestiging `START $8,50 CANARY`.
- De Hyperliquid-cloudwalletfallback uit build 228 blijft actief voor Live Positions, Risk en de achtergrondscanner.

## 2026-08-07

### [2.59-build228-test] - begrensde echte MEXC-canary
- Eerste echte BTC_USDT-canary heeft server-side een onoverschrijdbare limiet van $8,50 totale positieomvang.
- MEXC-contractvolume wordt altijd naar beneden afgerond; de order kan daardoor kleiner zijn maar nooit groter dan $8,50.
- Alleen isolated hedge-mode Long, maximaal één canary wanneer er nog geen BTC-positie bestaat.
- Unieke order-ID en persoonlijke Firestore-status voorkomen een onbedoelde dubbele canary.
- De gebruiker activeert REAL MONEY en drukt daarna afzonderlijk nogmaals om de canary expliciet te starten.
- De eerste canary gebruikt altijd 1x hefboom en een unieke externe order-ID; een onzekere netwerkstatus wordt nooit automatisch opnieuw besteld.
- Live Positions, Risk en de achtergrondscanner herstellen het gekoppelde Hyperliquid-adres uit het persoonlijke cloudaccount wanneer WalletConnect tijdelijk geen sessie meldt.
- Een geldig cloudadres wordt niet langer iedere seconde door een leeg WalletConnect-adres overschreven.

### [2.58-build227-test] - MEXC-cloudmigratie met lokale versleutelde reservekopie
- De bestaande MEXC API-koppeling wordt na expliciete toestemming naar de persoonlijke Google Secret Manager gekopieerd en gecontroleerd.
- De lokale kopie blijft versleuteld bewaard omdat voor verwijdering geen afzonderlijke toestemming is gegeven.
- Deze migratie plaatst geen orders en schakelt orderuitvoering niet automatisch in.

### [2.57-build226-test] - automatische veilige MEXC-sleutelmigratie
- Een reeds lokaal versleutelde MEXC API-koppeling wordt éénmalig naar de persoonlijke Secret Manager-cloudopslag verplaatst.
- De lokale kopie wordt uitsluitend verwijderd nadat MEXC de accountkoppeling en de cloudopslag succesvol hebben bevestigd.
- Gebruikers hoeven na deze update hun bestaande Secret Key niet opnieuw in te voeren.

### [2.56-build225-test] - persoonlijke MEXC-cloudkoppeling
- MEXC API-key en secret worden na een echte alleen-lezen controle per Firebase-gebruiker in Google Secret Manager opgeslagen; nooit in Firestore of logs.
- Cloudpreflight controleert Futures USDT-equity, available balance, open BTC-posities, hedge mode, actuele fees en toegestane leverage.
- Het Auto Trade-dashboard toont alleen `CLOUD GECONTROLEERD` wanneer MEXC de koppeling werkelijk heeft bevestigd.
- REAL MONEY gebruikt niet langer alleen een lokale sleutelstatus; activering vereist opnieuw een geslaagde persoonlijke cloudpreflight en expliciete bevestiging.
- Orderuitvoering blijft centraal vergrendeld tot de afzonderlijke gecontroleerde live-canary; buildtests plaatsen geen echte orders.

### [2.55-build224-test] - MEXC Adaptive DCA + Dynamic Hedge
- Nieuw Auto Trade-tabblad voor BTC_USDT MEXC Futures met aparte paper- en real-moneykeuze.
- Papertrading is standaard en heeft een vrij instelbaar fictief totaalvermogen; er worden geen echte orders verstuurd.
- Real money blijft veilig vergrendeld totdat API-rechten, cloudkoppeling, hedge mode, saldo, orderminimum, margin en liquidatieafstand zijn gecontroleerd.
- Instelbare execution-timeframes: 1m, 3m, 5m, 15m, 30m en 1h; standaard 3m.
- Instelbare risk/hedge-timeframes: 5m, 15m, 30m, 1h en 4h; standaard 15m.
- DCA, ATR, lower lows en prijsactie volgen het execution-timeframe; hedge, risk en recovery volgen het risk-timeframe.
- Positiegrootte, DCA-ladder, cooldown, take-profit, hedge en harde veiligheidsrails schalen vanaf sessievermogen.
- Vijf automatische testlagen geslaagd plus openbare MEXC-feedcontrole voor alle ondersteunde candle-intervallen; geen echte orders geplaatst.
- APK: `APK Releases/TradeMentor-Test-v2.55-build224.apk`.

### [2.54-build223-test] - rolling BTC-backtest en 3D-bediening
- Per tijdvak walk-forward backtest over maximaal de laatste 1.000 afgeronde echte BTC-candles.
- Iedere backtestregel toont Long/Short, startprijs, eindprijs, beweging en harde win/loss-uitkomst.
- Nieuwe voorspelling wordt automatisch vernieuwd na het gekozen tijdvak; bij 1 minuut dus iedere minuut.
- Historisch winstscenario bij de gekozen inzet gebruikt de gemiddelde winnende beweging minus geschatte retourkosten.
- Tijdvak- en Long/Short-bediening zijn uitgevoerd als verlichte fysieke cockpitschakelaars.
- APK: `APK Releases/TradeMentor-Test-v2.54-build223.apk`.

### [2.53-build222-test] - echte 3D Bitcoin-cockpit
- Vervangt de platte cockpitbenadering uit build 221 door de gekozen ruimtelijke 2028-cockpit (concept 6).
- Eerste-persoonsperspectief met aarde, gebogen cockpitramen, fysieke schermen en verlichte bedieningsconsole.
- Werkende tijdvak-, AI-, inzet-, Long/Short-, livepositie- en historiebediening blijft over de 3D-scene beschikbaar.
- APK: `APK Releases/TradeMentor-Test-v2.53-build222.apk`.

### [2.52-build221-test] - Bitcoin Trade Casino cockpit
- Nieuw afzonderlijk Bitcoin-tabblad in futuristische 2028-cockpitstijl (concept 6).
- Looptijden: 1 minuut, 5 minuten, 15 minuten, 1 uur, 4 uur en 1 dag; timer begint bij het bevestigde instapmoment.
- AI geeft per gekozen tijdvak altijd Long of Short, inclusief zichtbare zekerheid en reden.
- Live inzet, positiewaarde, winst/verlies, instapprijs, actuele BTC-prijs, timer en geschatte instapkosten.
- Automatische sluiting via een beveiligde Cloud Tasks-wachtrij, ook als app of telefoon uit staat.
- Handmatige sluiting, inzetgrenzen, saldo-controle, cooldown, een BTC-positie tegelijk en expliciete bevestiging.
- Per tijdvak maximaal de laatste 1.000 voorspellingen, gewonnen/verloren telling en apart succespercentage.
- Een eerdere algemene BTC-uitsluiting in het scannerpad is verwijderd; de serverbevestigde universumselectie is leidend.
- Cloudrevision: `tradementor-api-00037-6d9`; sluitwachtrij actief in `europe-west1`.
- APK: `APK Releases/TradeMentor-Test-v2.52-build221.apk`.
- Validatie: 21 cloudtests en alle Android `publicDebug`-unit-tests geslaagd; geen echte order geplaatst.

### [2.51-build220-test] — bevestigde goede terugvalversie
- Door Amar op 7 augustus 2026 bevestigd als laatst werkende goede testversie.
- APK: `APK Releases/TradeMentor-Test-v2.51-build220.apk`.
- Geïnstalleerd en versie gecontroleerd op beide aangesloten Samsung-testtoestellen.
- DCA Pulse is de standaardstrategie bij een schone installatie.
- Actieve posities kunnen worden gesorteerd op werkelijke prijsbeweging en positiegrootte in dollars.
- DCA-tellers worden centraal vanuit de persoonlijke cloud gesynchroniseerd.
- Bekende verbeterpunten mogen later worden opgepakt; wijzigingen moeten eerst tegen deze versie worden gecontroleerd.

### [2.46-build215-test]
- DCA top-universum en max actieve deals ondersteunen nu willekeurige waarden van 1 t/m 500; 150 deals wordt niet meer verborgen teruggezet naar 100.
- Een cache van een andere Top-N-grootte kan nooit stilletjes worden hergebruikt; onvolledige universumdata blokkeert orders en toont een concrete fout.
- Scannerstatus toont voortaan hoeveel op Hyperliquid verhandelbare markten werkelijk zijn gescand ten opzichte van het ingestelde universum.
- Interne simulatie met top 200 en 150 vrije deals vult 150 neporders in een 75 LONG / 75 SHORT-balans, zonder echte transacties.
- Close All-doel ondersteunt 1 t/m 1000 procent; +80% en +300% zijn gesimuleerd met een vaste cyclus-startwaarde.
- Close All sluit bij doelbereik werkelijk alle open posities reduce-only en houdt mislukte sluitingen zichtbaar; getest met een nep-exchange.
- Elke actieve positiekaart heeft op de voorkant een `CLOSE POSITION`-knop met expliciete bevestiging voor groene én rode posities.

### [2.45-build214-test]
- Alle DCA-invoervelden op Strategy en Live Positions gebruiken nu één centrale omzettings- en opslagbron.
- Teruggaan of sluiten vanuit een DCA-instellingenscherm slaat wijzigingen expliciet op; ingevoerde waarden verdwijnen niet stilzwijgend.
- Ongeldige of lege tekst in één veld kan geen andere DCA-waarde meer terugzetten naar een standaardwaarde.
- Top-universum is dynamisch van 1 t/m 500; het exacte getal wordt aan scanner én cloud-ordercontrole doorgegeven.
- Het cloud-universumendpoint accepteert dezelfde dynamische universumgrootte in plaats van een verborgen vaste keuze.
- Automatische tests dekken alle DCA-velden, gedeelde waardekoppeling, grenzen 1–500 en willekeurige invoer zoals 137.

## 2026-08-06

### [2.44-build213-test]
- DCA-actieve deals gebruiken voortaan alle werkelijk open Hyperliquid-posities als enige bron: 4 LONG + 7 SHORT wordt 11/maximum.
- De fout waarbij het DCA-overzicht `0/50` kon tonen terwijl LONG/SHORT samen 11 waren is opgelost.
- DCA Pulse blijft bij vrije capaciteit automatisch aanvullen met een vervolgscan na 1 minuut.
- Bij een volledig gevulde capaciteit schakelt de scanner over op de bestaande controle per minimaal 15 minuten.
- De scanner toont tijdens het wachten `automatische vervolgscan` in plaats van de misleidende status `Ruststand`.
- Reproductietests toegevoegd voor 11/50 en 50/50; geen echte orders gebruikt tijdens validatie.

### [2.43-build212]
- Buildregels herbevestigd:
  - projectpad: `C:\HyperEdge\Android\TradeMentor`
  - 1 publieke + 1 test releasepad
  - harde afspraken vastgelegd in `docs/HARD_AGREEMENTS.md`
- Hardcoded fallback naar debug-output moet in de buildworkflow expliciet geaccepteerd of uitgeschakeld zijn.
- Locatie referentie voor APK-uitgifte:
  - `APK Releases`
- Overleg uit deze sessie: prioriteit ligt op stabiliteit van testproces en duidelijke versie- en buildlogging.
