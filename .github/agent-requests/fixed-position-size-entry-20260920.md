# DEFINITIEVE DEVELOPER-OPDRACHT — OPTIONELE VASTE POSITIEOMVANG + SETTINGS-SYNC + LONG-REFILL CONTROLE

Werk in de huidige live Amar Crypto Bot 2026 / V46-webapp en backend.

## Aanleiding
In build 379 zijn twee nieuwe posities gezien met hetzelfde ingestelde bedrag/margin van ongeveer $0,30, maar met verschillende leverage:
- ARB LONG 20x -> circa $6 notional.
- ENA SHORT 50x -> circa $15 notional.

Daardoor leveren posities met lagere leverage bij dezelfde margin een veel kleinere werkelijke positieomvang en dus een kleinere PnL-bijdrage. Dit moet optioneel anders kunnen.

## Nieuwe keuze: Vaste positieomvang
Voeg in Botinstellingen een duidelijke AAN/UIT-schakelaar toe met de naam **Vaste positieomvang**.

Tekst:
**Aan:** instapbedrag = totale positie in USDT. Benodigde margin = positie ÷ leverage.
**Uit:** instapbedrag = margin; de positieomvang verandert mee met leverage.

De schakelaar moet standaard UIT blijven voor bestaande gebruikers, tenzij hun opgeslagen entrySizingMode al `notional` is. Geen bestaande accountconfig mag stilzwijgend worden gemigreerd.

Wanneer AAN:
- LONG- en SHORT-instapbedrag zijn gewenste notional/positieomvang.
- Voorbeeld: $6 positie -> 20x = $0,30 margin; 50x = $0,12; 100x = $0,06.
- De werkelijke order-notional blijft zo dicht mogelijk bij het gekozen instapbedrag, rekening houdend met exchange quantity-step/minimum-notional regels.
- Minimum/Maximum leverage blijven uitsluitend leveragefilters/caps; zij veranderen het gekozen positiebedrag niet.
- LONG en SHORT mogen hun eigen positiebedrag houden.

Wanneer UIT:
- bestaand gedrag exact behouden: LONG/SHORT instapbedrag is margin.
- notional = margin × gekozen leverage.

## UI
- Gebruik een compacte premium switch in dezelfde stijl als de bestaande Botinstellingen.
- Bij AAN moeten de LONG/SHORT labels duidelijk maken dat het om **positie USDT** gaat.
- Bij UIT moeten de labels duidelijk maken dat het om **margin USDT** gaat.
- Geen extra scherm of wizard.
- Header/buildinformatie moet naar de nieuwe build worden bijgewerkt.
- “Niet opgeslagen” mag na een door de server bevestigde save niet blijven staan.
- Maximum leverage moet na opslaan en herladen zichtbaar blijven als die daadwerkelijk server-side is opgeslagen.

## Persistente data
Bewaar expliciet:
- entrySizingMode
- entryMarginLongUsd / entryMarginShortUsd
- entryNotionalLongUsd / entryNotionalShortUsd
- entryNotionalUsd als backward-compatible LONG/shared alias
- maximumLeverage en bestaande Stoploss-velden.

Oude/global editors mogen deze nieuwe velden niet per ongeluk wissen.

## Backend
Gebruik de reeds bestaande `notional` sizing-path in de Multi-BB engine. Breid de side-aware instellingen uit zodat LONG en SHORT ieder hun eigen notional kunnen hebben.

De required margin moet worden afgeleid als:
`requiredMargin = plannedNotional / actualLeverage`.

Smart Rescue moet bij vaste positieomvang als startmargin gebruiken:
`LONG position notional / actual entry leverage`,
niet het oude marginveld.

DCA-logica zelf niet functioneel veranderen.

## Leverage preview / simulatie
De read-only leverage preview moet zowel margin- als notional-mode kunnen simuleren.
De veilige simulatie moet expliciet tonen welke sizing-mode actief is en voor voorbeeldleverages bewijzen dat notional constant blijft als Vaste positieomvang AAN staat. Er mogen 0 orders worden verzonden.

## Bestaand onderzoek gebruiker
Controleer daarnaast read-only de gemelde build-379 situatie met 20 slots (10 LONG/10 SHORT), Top-N 50 en vrije LONG-slots:
- waarom vrije LONG-slots niet direct werden gevuld;
- of Bollinger 15m kandidaten werkelijk blokkeerde;
- welke LONG entries/rejects in circa 15/30/60 minuten zichtbaar waren;
- of ARB/ENA inderdaad recent zijn ingestapt en met welke leverage/notional/margin;
- welke maximumLeverage op dat moment server-side was opgeslagen;
- configHistory rond maximumLeverage en entrySizingMode;
- waarom UI “Niet opgeslagen” kon tonen en maximum leverage kon verdwijnen.

Gebruik voor accountdiagnose alleen een unieke instellingenfingerprint en publiceer geen e-mail, UID, walletadres, private key of order-signingsecret.

## Verplichte regressietests
Minimaal:
1. $6 notional @20x -> circa $0,30 required margin.
2. $6 notional @50x -> circa $0,12 required margin.
3. Beide houden dezelfde planned notional.
4. Margin mode blijft bestaand gedrag houden.
5. LONG en SHORT side-specific notional blijven onafhankelijk.
6. Maximum leverage blijft werken in beide modes.
7. Save/reload bewaart sizing toggle en maximum leverage.
8. “Niet opgeslagen” verdwijnt na bevestigde save.
9. Smart Rescue startmargin wordt bij notional-mode uit actual leverage afgeleid.
10. Bestaande DCA/TP/Stoploss/Profit Lock tests blijven groen.

## Release
- Nieuwe V46 build.
- Volledige backend pytest-suite.
- Volledige web build + regressiesuite.
- Veilige simulatie: 0 orders.
- Backend als candidate deployen, healthcheck, pas daarna productie.
- Web candidate bouwen, verifiëren en pas daarna 100% verkeer.
- Rollback behouden.
- Pas melden dat het live staat nadat backend- en webproductie zijn geverifieerd.
