# Webapp release history policy

Vanaf V46 build 373 geldt voor iedere productie-update van de webapp:

1. Iedere echte live webwijziging krijgt een nieuw, hoger `WEBAPP_BUILD_NUMBER`.
2. Dezelfde wijziging krijgt een begrijpelijke entry in `web/lib/release-history.ts`.
3. De release-entry beschrijft waar relevant: nieuw, probleem, oorzaak, oplossing, huidige werking en voor/na.
4. Oorzaken worden alleen vastgelegd wanneer ze aantoonbaar bekend zijn.
5. Pre-GitHub historie krijgt `confidence: "reconstructed"` wanneer exacte buildinformatie niet meer bewezen kan worden.
6. Bevestigde Git/build/deploymenthistorie krijgt `confidence: "confirmed"`.
7. De deploymentworkflow controleert vóór productie dat het buildnummer hoger is dan de live build en dat buildnummer + release-history in dezelfde webrelease zijn aangepast.
8. Tradingstrategie, orderlogica, wallets, secrets en accountdata mogen nooit in een release-entry worden gewijzigd of blootgelegd.

De zichtbare versie rechtsboven, PWA-update-identiteit en versiegeschiedenis gebruiken dezelfde centrale bron:
`web/lib/app-version.ts`.

Doel: geen enkele toekomstige live webwijziging mag verdwijnen uit de ontwikkelgeschiedenis.
