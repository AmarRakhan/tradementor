export default function LegalPage() {
  return <main className="legal-shell">
    <article className="legal-document">
      <header><img src="/tradementor-logo.png?v=redgreen-1" alt="TradeMentor" /><div><span>TRADEMENTOR WEB</span><h1>Privacy, voorwaarden en handelsrisico</h1></div></header>
      <p className="legal-updated">Versie 1.0 · laatst bijgewerkt 8 augustus 2026</p>
      <section><h2>Belangrijk handelsrisico</h2><p>Handelen in crypto en futures kan leiden tot snel en volledig verlies van het ingelegde vermogen. Hefboom vergroot zowel winst als verlies. TradeMentor garandeert geen winst en historische resultaten voorspellen geen toekomstige resultaten.</p><p>Automatische handel staat standaard uit. De gebruiker moet een exchange persoonlijk koppelen, de controle doorlopen en echt-geldhandel bewust activeren. Controleer orders en posities altijd rechtstreeks bij de exchange; die administratie is leidend.</p></section>
      <section><h2>Wat TradeMentor doet</h2><p>TradeMentor toont exchangegegevens, kan strategieën simuleren en kan na expliciete activering handelsopdrachten naar een gekoppelde exchange sturen. Beschikbaarheid van functies kan per exchange verschillen. Aster is in deze versie alleen-lezen totdat de live-engine afzonderlijk is vrijgegeven.</p></section>
      <section><h2>Persoonlijke verantwoordelijkheid</h2><p>Gebruik alleen geld dat je volledig kunt missen. De gebruiker kiest zelf instellingen, limieten en activering. Storingen, vertragingen, koerssprongen, liquiditeit, fees en exchangeproblemen kunnen ervoor zorgen dat uitvoering afwijkt of niet plaatsvindt.</p></section>
      <section><h2>Privacy en accountscheiding</h2><p>Identiteit wordt beheerd met Firebase Authentication. Walletadressen, instellingen en handelsadministratie worden per unieke gebruikers-ID opgeslagen. API- en agentgeheimen worden server-side in Google Secret Manager bewaard en worden na koppeling niet teruggestuurd naar de browser.</p><p>TradeMentor gebruikt gegevens die nodig zijn voor accounttoegang, exchangeverbindingen, portefeuilleweergave, strategie-uitvoering, foutonderzoek en beveiliging. Geheimen horen nooit in een bugrapport of chatbericht.</p></section>
      <section><h2>Beveiliging</h2><p>E-mailverificatie is vereist voordat echt-geldhandel kan worden geactiveerd. Handelsopdrachten gebruiken persoonlijke en centrale veiligheidspoorten, idempotente order-ID’s en risicocontroles. Geen enkel technisch systeem kan ieder risico uitsluiten.</p></section>
      <section><h2>Abonnementen</h2><p>Premium-betalingen zijn nog niet geactiveerd. Zolang geen checkout en prijs expliciet worden aangeboden, ontstaat geen betaald abonnement via deze webapp.</p></section>
      <section><h2>Stoppen en gegevens</h2><p>De gebruiker kan livehandel en scanners uitschakelen. Open posities verdwijnen daardoor niet automatisch: controleer en sluit die waar nodig bij de exchange. Verzoeken over accountgegevens kunnen via de beheerder worden ingediend.</p></section>
      <a className="legal-back" href="/">Terug naar TradeMentor</a>
    </article>
  </main>;
}
