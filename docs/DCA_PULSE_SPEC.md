# DCA Pulse teststrategie (v2.42 build 210)

DCA Pulse is exclusief: zodra strategie 3 actief is, gebruikt Scan & Buy uitsluitend onderstaande regels en instellingen.

## Door gebruiker instelbaar

- basisorder in USD; iedere bijkoop gebruikt exact hetzelfde bedrag;
- long-afstand per DCA-niveau vanaf de oorspronkelijke instap;
- short-afstand per DCA-niveau vanaf de oorspronkelijke instap;
- maximaal aantal bijkopen per actieve pair;
- maximaal aantal unieke actieve deals;
- tijd tussen bijkopen, instelbaar in minuten of uren;
- Close All-portfoliodoel, standaard 10% per handmatig gestarte cyclus.

## Eerste aankoop

Alleen markten binnen de actuele serverbevestigde Aster USDT Top-N mogen een basisdeal starten. Binnen dat universum mag de strategie haar eigen richting en instapsignaal bepalen. Een stijger is uitsluitend long-kandidaat en moet met de actuele mark price onder de onderste BB(20,2) op gesloten 1-minuutcandles staan. Een daler is uitsluitend short-kandidaat en moet boven de bovenste band staan.

Long en short zijn altijd beide actief. Nieuwe unieke deals worden alleen toegelaten wanneer het verschil tussen het aantal long- en shortpairs na instap maximaal drie blijft. Positiegrootte beïnvloedt deze balanspoort niet.

Het basisorderbedrag is notional. De bot gebruikt automatisch de actuele maximale Hyperliquid-hefboom van de pair zonder het ingestelde orderbedrag nogmaals te vermenigvuldigen.

## Bijkopen

Een actieve pair kan niet opnieuw als basisdeal worden gekozen. Hij kan uitsluitend in zijn oorspronkelijke richting bijkopen. Lidmaatschap van het actuele Top-N-universum wordt na de basisorder niet opnieuw vereist.

De ladder blijft verankerd aan de oorspronkelijke fill. Bij long 2% zijn de niveaus 98%, 96%, 94% enzovoort. Bij short 8% zijn dit 108%, 116%, 124% enzovoort. Een niveau wordt maximaal eenmaal uitgevoerd en per scan wordt maximaal één DCA-order per pair geplaatst. Ook voor de bijkoop moet de overeenkomstige 1-minuut-Bollinger-voorwaarde gelden.

Een verhoging van het maximum geldt direct voor lopende deals, maar veroorzaakt geen onmiddellijke orders. Nieuwe stappen wachten op hun eigen prijs- en Bollingerconditie.

## Uitstappen en portfoliocyclus

DCA Pulse plaatst geen automatische normale take-profit, trailing take-profit of stop-loss. Normale posities worden handmatig gesloten.

Bij handmatig starten van Scan & Buy bewaart de cloud een vaste startportfoliowaarde en het gekozen doel. Het doel kan tijdens de actieve cyclus alleen worden verhoogd; de startwaarde verandert niet. De app toont startwaarde, huidige waarde, doelwaarde, groei, resterend bedrag en de actuele notionele long- en shortdollars.

Zodra de totale accountwaarde het doel bereikt, claimt de cloud de actie één keer, schakelt Scan & Buy uit, sluit alle posities, annuleert resterende orders en vergrendelt de cyclus. Alleen een nieuwe handmatige start maakt een nieuwe cyclus met een nieuwe startwaarde.

Dit is een experimentele teststrategie. Resultaten of historische prestaties zijn geen winstgarantie.
