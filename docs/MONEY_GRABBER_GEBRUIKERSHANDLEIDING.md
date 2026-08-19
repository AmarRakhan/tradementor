# Money Grabber – Portfoliorondes

## Wat was er eerst aan de hand?

De oude Portfolio Protection werkte vooral als algemene noodrem. Bij oplopende
drawdown of margin kon Strategy 2 nieuwe risicoacties blokkeren, maar een
afzonderlijke verliezende munt kreeg niet automatisch een tegengestelde positie
op exact hetzelfde symbool. Daardoor konden meerdere verliezers samen de
walletwaarde sterk verlagen. Ook bestond er geen automatisch einde van een
winstgevende portfolioronde.

## Wat is Money Grabber?

Money Grabber is een optionele uitbreiding van Strategy 2. De functie staat
standaard uit. Vrije LONG- en SHORT-posities proberen zelfstandig winst te
maken en LONG- en SHORT-DCA blijven afzonderlijk instelbaar.

Wanneer een positie de ingestelde beschermingsgrens bereikt, kan Money Grabber
op hetzelfde symbool een positie in de tegengestelde richting opbouwen. Eerst
gedeeltelijk en, wanneer nodig, volledig. Beide kanten vormen daarna één
gekoppeld paar. Normale entry, DCA, losse take-profit en auto-reopen zijn voor
dat beschermde symbool geblokkeerd. Andere vrije munten kunnen ondertussen
blijven handelen.

## Money Grabber aanzetten

1. Open Strategy 2 en daarna de Strategy Maker.
2. Stel basisbedrag, take-profit, leverage, marginmodus en budget in.
3. Stel LONG-DCA afzonderlijk in.
4. Stel SHORT-DCA afzonderlijk in.
5. Zet **Money Grabber – Portfoliorondes** aan.
6. Vul het portfoliodoel in, bijvoorbeeld 5%.
7. Kies eventueel automatisch Alles sluiten en opnieuw beginnen.
8. Sla de instellingen op. Dit plaatst nog geen order.
9. Open **Nieuwe Money Grabber-ronde starten**.
10. Controleer equity, netto startwaarde, doelwaarde, bestaande posities en
    beschermingsreserve.
11. Bevestig alleen wanneer de preview meldt dat alle veiligheidsgegevens
    betrouwbaar zijn.

## Wat gebeurt er daarna?

- Vrije symbolen handelen volgens de normale Strategy-2-regels.
- Een protection-fill telt niet als DCA en verandert geen DCA-teller.
- Een gedeeltelijk beschermd of locked symbool krijgt geen normale DCA.
- Een beschermd paar mag alleen gezamenlijk sluiten wanneer het nettoresultaat
  na fees, funding en slippage boven de winstbuffer ligt.
- Na gezamenlijke sluiting volgt minimaal één betrouwbare cooldownscan voordat
  het symbool weer vrij is.
- Wanneer de verwachte netto portefeuillewaarde het rondedoel plus buffer
  bereikt, blokkeert de ronde nieuwe risicoacties en kan Alles sluiten starten.
- Een nieuwe ronde begint pas na bevestigde nulposities en nul relevante open
  orders. De werkelijke eindwaarde wordt de nieuwe startwaarde.

## Rekenvoorbeeld

De netto startwaarde is US$100 en het doel is 5%. De netto doelwaarde is dan
US$105. Een zichtbare equity van US$105,30 is niet voldoende wanneer fees en
slippage US$0,40 kosten: de verwachte netto waarde is slechts US$104,90.

Later toont de exchange US$105,70 en is de verwachte netto waarde US$105,25.
Het doel is dan bereikt. Na gecontroleerd sluiten blijkt de werkelijke
eindwaarde bijvoorbeeld US$105,12. De volgende ronde start op US$105,12 en het
volgende 5%-doel is ongeveer US$110,38.

## Eerlijke waarschuwing

Een volledige gelijke hedge wist bestaand verlies niet uit; hij bevriest vooral
verdere koersschade. Fees, funding, slippage, margin en liquidatie blijven
relevant. Gedeeltelijke bescherming laat herstel toe, maar beschermt niet
volledig. Andere vrije munten moeten locked verlies en kosten terugverdienen.
Een portfoliodoel of hedge garandeert geen winst. Automatische financiële
acties mogen uitsluitend starten met actuele, betrouwbare en bevestigde
exchangegegevens.

## Teststatus

De testversie toont de wizard, instellingen, previewflow en read-only
shadowstatus. Exchange-uitvoering blijft centraal uit totdat de afzonderlijke
backendpublicatie, shadowvalidatie en Hedge Mode-controle volledig zijn
afgerond. De schakelaar aanzetten mag in deze fase daarom niet worden gezien
als toestemming voor echte Money Grabber-orders.
