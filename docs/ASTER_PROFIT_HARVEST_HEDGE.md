# Aster Profit Harvest Hedge

## Doel

De strategie gebruikt per pair een LONG en SHORT als basishedge en probeert marktbewegingen te oogsten zonder open verlies te verbergen. Historische of gesimuleerde prestaties zijn geen winstgarantie.

## Standaardinstellingen

- Positieomvang: 10 USD per kant.
- Cross Margin en maximale leverage die Aster voor het contract toestaat.
- Maximaal 5 actieve pairs; iedere actieve pair is uitgesloten van nieuwe selectie.
- Aster USDT Top-N op 24-uurs quotevolume en liquiditeit; ieder positief geheel getal blijft exact opgeslagen.
- Scannercontrole: iedere minuut.
- LONG DCA: iedere 2% vanaf de oorspronkelijke instapprijs.
- SHORT DCA: iedere 5% vanaf de oorspronkelijke instapprijs.
- Maximaal 3 bijkopen per kant; iedere bijkoop 1× de basisorder.
- Winstoogst: 0,5% netto over de volledige gewogen kant, na kosten en funding.
- 50% gerealiseerde winst naar veiligheidsbuffer en 50% naar de momentum-pot.

## Openen

De bot opent per pair eerst LONG, controleert de exchange-bevestiging en opent daarna SHORT. Mislukt SHORT, dan wordt LONG onmiddellijk gecompenseerd. Een onbekende uitvoeringsstatus wordt nooit blind opnieuw verzonden. Een exchange-minimum mag het ingestelde orderbedrag niet stilzwijgend vergroten.

## DCA en winstoogst

DCA-niveaus blijven verankerd aan de oorspronkelijke instap. Na DCA wordt het winstdoel berekend vanaf de gewogen gemiddelde instapprijs. Bij behalen sluit de bot de hele winstgevende kant en opent dezelfde richting opnieuw met de basisorder. De andere kant blijft bestaan.

## Budget en noodrem

- Botbudget: standaard maximaal 50% van de Aster-portfoliowaarde.
- Pairbudget: gelijke verdeling met standaard 5% speling.
- Vanaf 50% marginratio: geen nieuwe entries of DCA.
- Vanaf 70%: momentumherinvestering stopt en winstgevende exposure wordt geoogst.
- Vanaf 80%: de noodrem mag ook verliesgevende exposure sluiten om liquidatie te voorkomen.
- Bij 5% cyclusdrawdown pauzeren nieuwe pairs; bestaande DCA mag alleen binnen budget en onder de marginlimiet doorgaan.

## Stoppen

Veilig stoppen blokkeert nieuwe entries en DCA, maar blijft bestaande posities bewaken. Alles sluiten vereist een afzonderlijke tweede bevestiging en toont vooraf verwacht resultaat, kosten en verlies.

## Herstel

Na een storing of herstart wordt eerst de volledige exchange-state herbouwd: posities, open orders, fills, DCA-aantallen en gemiddelde instapprijzen. Bij een verschil blijft nieuw risico geblokkeerd; risicoverlagende acties blijven beschikbaar.
