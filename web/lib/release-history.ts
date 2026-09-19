import { WEBAPP_BUILD_NUMBER, WEBAPP_VERSION } from "@/lib/app-version";

export type ReleaseConfidence = "confirmed" | "reconstructed";

export type ReleaseHistoryEntry = {
  id: string;
  version: string;
  build: string | null;
  releasedAt: string;
  title: string;
  newItems: string[];
  problems: string[];
  causes: string[];
  fixes: string[];
  now: string[];
  before?: string;
  after?: string;
  technicalDetails?: string[];
  confidence: ReleaseConfidence;
};

export const CURRENT_RELEASE: ReleaseHistoryEntry = {
  id: "v46-build-373-release-history",
  version: WEBAPP_VERSION,
  build: WEBAPP_BUILD_NUMBER,
  releasedAt: "2026-09-19",
  title: "Versiegeschiedenis en app-ontwikkellogboek",
  newItems: [
    "Mobiele versiegeschiedenis met nieuwste release bovenaan.",
    "Ongelezen badge bij de knop linksboven.",
    "Zoeken in oude releases, problemen en oplossingen.",
  ],
  problems: [
    "Gebruikers konden niet centraal terugvinden wat tussen appreleases veranderde en waarom.",
  ],
  causes: [
    "De bestaande versieknop controleerde alleen op updates; release-uitleg stond verspreid over commits, chats en technische notities.",
  ],
  fixes: [
    "Eén centrale releasebron toegevoegd met probleem, oorzaak, oplossing, voor/na en technische context per release.",
    "De linkerbovenhoek opent nu het mobiele ontwikkellogboek zonder de huidige pagina te verlaten.",
    "Buildnummer en releasehistorie zijn aan één releasecontract gekoppeld.",
  ],
  now: [
    "Nieuwe releases zijn direct herkenbaar en blijven later terugleesbaar.",
    "De gebruiker ziet hoeveel nieuwe builds nog niet zijn gelezen.",
    "Iedere volgende live webupdate moet een nieuw buildnummer én release-entry krijgen.",
  ],
  before: "De tekst CRYPTO BOT 2026 was statisch en de releasehistorie was niet vanuit de app bereikbaar.",
  after: "De linkerbovenhoek is een knop Versiegeschiedenis met een ongelezen teller en een volledig mobiel logboek.",
  technicalDetails: [
    "Alleen web-UI, versieadministratie en deploymentcontract gewijzigd.",
    "Leesstatus wordt lokaal en persistent in de PWA/browser opgeslagen; tradingstate wordt niet aangeraakt.",
    "Centrale bron: web/lib/release-history.ts.",
    "CI/deployment controleert buildnummer en release-entry vóór promotie.",
  ],
  confidence: "confirmed",
};

const HISTORICAL_RELEASES: ReleaseHistoryEntry[] = [
  {
    id: "v46-build-372-baseline",
    version: "46",
    build: "372",
    releasedAt: "2026-09-19",
    title: "V46-productiebasis vóór centraal ontwikkellogboek",
    newItems: ["Bestaande V46 mobiele productie draaide als build 372."],
    problems: ["Er was nog geen centrale, gebruikersleesbare versiegeschiedenis."],
    causes: ["De zichtbare versieknop was uitsluitend bedoeld om een nieuwere appbuild te controleren."],
    fixes: [],
    now: ["Dit is de laatste bevestigde V46-basis vóór de introductie van het nieuwe logboek in build 373."],
    technicalDetails: ["Bevestigde live V46-buildweergave."],
    confidence: "confirmed",
  },
  {
    id: "v46-github-first-control-plane",
    version: "46",
    build: null,
    releasedAt: "2026-09-19T14:23:27+02:00",
    title: "GitHub-first ontwikkeling en deployment bewezen",
    newItems: ["Normale ontwikkeling, diagnose en deployment kunnen via GitHub zonder dagelijkse Cloud Workstation-koppeling."],
    problems: ["Ontwikkelwerk kon stilvallen wanneer een tijdelijke cloud/workstationverbinding wegviel."],
    causes: ["Dagelijkse ontwikkeling leunde te veel op rechtstreekse cloudtoegang."],
    fixes: ["GitHub Actions, WIF, candidate-checks, rollback en GitHub-only productie-diagnostiek ingericht en end-to-end bewezen."],
    now: ["Normale UI- en backendwijzigingen lopen via GitHub; Workstation is alleen nog break-glass."],
    technicalDetails: ["Bevestigd door GitHub-only deployment proof #154 en post-deploy health proof #155."],
    confidence: "confirmed",
  },
  {
    id: "smart-rescue-20260914",
    version: "46",
    build: null,
    releasedAt: "2026-09-14",
    title: "Smart Rescue DCA ontworpen en geïntegreerd",
    newItems: ["Smart Rescue DCA als aanvullende herstelmodus."],
    problems: ["Verliesposities hadden behoefte aan gecontroleerder herstel dan alleen vaste DCA-stappen."],
    causes: [],
    fixes: ["Herstellogica en bijbehorende instellingen als aparte, optionele module uitgewerkt."],
    now: ["De app kan een slimmere herstelroute aanbieden zonder bestaande modi te vervangen."],
    confidence: "reconstructed",
  },
  {
    id: "profit-lock-ladder-20260911",
    version: "46",
    build: null,
    releasedAt: "2026-09-11",
    title: "Profit Lock Ladder toegevoegd als optionele modus",
    newItems: ["Profit Lock Ladder met eigen aan/uit-keuze."],
    problems: ["Winstbescherming moest kunnen meegroeien zonder bestaande tradingmodi te vervangen."],
    causes: [],
    fixes: ["Nieuwe LONG-only modus ontworpen waarbij SHORT-posities uitsluitend als beschermingslaag dienen."],
    now: ["Gebruikers kunnen winstbescherming activeren zonder de bestaande standaardmodi kwijt te raken."],
    confidence: "reconstructed",
  },
  {
    id: "tradecentrum-20260903",
    version: "46",
    build: null,
    releasedAt: "2026-09-03",
    title: "Tradecentrum uitgebreid met winstsluiting en DCA-inzicht",
    newItems: ["Bulkactie voor winstgevende posities en extra sortering op DCA-activiteit."],
    problems: ["Kleine winsten vrijmaken kostte te veel losse handelingen en actieve posities waren lastiger te prioriteren."],
    causes: [],
    fixes: ["Tradecentrum uitgebreid met compacte winstactie en duidelijkere rangschikking."],
    now: ["Winstgevende posities en veelvuldig bijgezochte posities zijn sneller te herkennen en te beheren."],
    confidence: "reconstructed",
  },
  {
    id: "markets-risk-20260902",
    version: "46",
    build: null,
    releasedAt: "2026-09-02",
    title: "Markets-overzicht en liquidatierisico uitgebreid",
    newItems: ["Markets-overzicht, Bollinger-status en afzonderlijke liquidatierisico-indicatie."],
    problems: ["Marktselectie en liquidatieafstand waren niet snel genoeg in één oogopslag te beoordelen."],
    causes: [],
    fixes: ["Marktinformatie, sortering en risicometers als aparte visuele signalen toegevoegd."],
    now: ["Gebruikers zien marktcontext en liquidatiegevaar sneller naast de tradinginformatie."],
    confidence: "reconstructed",
  },
  {
    id: "manual-markets-20260831",
    version: "46",
    build: null,
    releasedAt: "2026-08-31",
    title: "Handmatige muntkeuze toegevoegd",
    newItems: ["Zelf munten kiezen met LONG/SHORT-richting per markt."],
    problems: ["Automatische selectie bood niet genoeg controle voor gerichte tests en specifieke markten."],
    causes: [],
    fixes: ["Een optionele handmatige marktselectie naast de bestaande automatische selectie toegevoegd."],
    now: ["Gebruikers kunnen specifieke munten en richting kiezen zonder de automatische flow te verwijderen."],
    confidence: "reconstructed",
  },
  {
    id: "android-239-build-207-github-migration",
    version: "2.39",
    build: "207",
    releasedAt: "2026-08-05T19:56:29+02:00",
    title: "Android-project naar GitHub en cloudmigratie gebracht",
    newItems: ["De bestaande TradeMentor Android-code werd als eerste GitHub-snapshot vastgelegd."],
    problems: ["De app bestond al lokaal, maar had nog geen centrale Git-geschiedenis voor de verdere cloudmigratie."],
    causes: ["Ontwikkeling vond vóór deze stap buiten de huidige GitHub-repository plaats."],
    fixes: ["Projectcode, Android-app, serveronderdelen en migratie-instructies in GitHub opgenomen."],
    now: ["Vanaf dit punt is de ontwikkelgeschiedenis rechtstreeks uit Git-commits te reconstrueren."],
    technicalDetails: [
      "Eerste bevestigde Git-commit: d8dae028f79cb831e6f23d209ba220b3f7c253e6.",
      "Snapshot bevatte Android versionName 2.39 en versionCode 207.",
    ],
    confidence: "confirmed",
  },
  {
    id: "local-v162-build80-20260802",
    version: "1.62",
    build: "80",
    releasedAt: "2026-08-02",
    title: "Vroege lokale app groeide naar circa build 80",
    newItems: ["De lokale Android-app was inmiddels uitgegroeid tot een veel bredere tradingapp."],
    problems: [],
    causes: [],
    fixes: [],
    now: ["Deze mijlpaal is uit pre-GitHub projecthistorie gereconstrueerd."],
    confidence: "reconstructed",
  },
  {
    id: "early-v001-20260729",
    version: "001",
    build: null,
    releasedAt: "2026-07-29",
    title: "Eerste werkende TradeMentor-builds",
    newItems: ["Eerste werkende appbouw en vroege releaseplanning."],
    problems: [],
    causes: [],
    fixes: ["Blueprint, projectstatus en changelogstructuur werden gebruikt om de ontwikkeling te ordenen."],
    now: ["Exacte afzonderlijke buildnummers uit deze pre-GitHub fase zijn niet allemaal hard te bewijzen."],
    confidence: "reconstructed",
  },
  {
    id: "project-start-20260728",
    version: "0.1.0-dev",
    build: "1",
    releasedAt: "2026-07-28",
    title: "Start van TradeMentor / Crypto Bot 2026",
    newItems: ["Eerste Android-project en basisarchitectuur opgezet."],
    problems: ["Er bestond nog geen gezamenlijke tradingapp."],
    causes: [],
    fixes: ["De eerste mobiele basis voor scanner, portfolio, strategie- en risicofuncties werd opgezet."],
    now: ["Dit is de oudste gereconstrueerde appmijlpaal in de huidige projecthistorie."],
    confidence: "reconstructed",
  },
];

function releaseTime(value: string) {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function buildNumber(entry: ReleaseHistoryEntry) {
  const parsed = Number(entry.build);
  return Number.isFinite(parsed) ? parsed : -1;
}

export function getReleaseHistory(): ReleaseHistoryEntry[] {
  const historical = [...HISTORICAL_RELEASES].sort((a, b) => {
    const dateDifference = releaseTime(b.releasedAt) - releaseTime(a.releasedAt);
    return dateDifference || buildNumber(b) - buildNumber(a);
  });
  return [CURRENT_RELEASE, ...historical];
}

export function releaseSearchText(entry: ReleaseHistoryEntry) {
  return [
    entry.version,
    entry.build || "",
    entry.title,
    ...entry.newItems,
    ...entry.problems,
    ...entry.causes,
    ...entry.fixes,
    ...entry.now,
    entry.before || "",
    entry.after || "",
    ...(entry.technicalDetails || []),
  ].join(" ").toLocaleLowerCase("nl-NL");
}
