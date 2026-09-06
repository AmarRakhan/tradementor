import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AuthProvider } from "@/components/auth-provider";
import { PwaRegistration } from "@/components/pwa-registration";
import { ZoomGuard } from "@/components/zoom-guard";
import { AppVersionControl } from "@/components/app-version-control";
import { Strategy2ReferenceEnhancer } from "@/components/strategy2-reference-enhancer";
import { MarketsNavigationBridge } from "@/components/markets-navigation-bridge";
import { AsterPairSettingsOverlay } from "@/components/aster-pair-settings-overlay";
import { AsterSideTpSettings } from "@/components/aster-side-tp-settings";
import { AsterShortDcaSaveGuard } from "@/components/aster-short-dca-save-guard";
import { AavanshBranding } from "@/components/aavansh-branding";
import { WEBAPP_VERSION } from "@/lib/app-version";
import "./globals.css";
import "./premium.css";
import "./premium-next.css";
import "./suriname-heritage.css";
import "./aster-tables.css";
import "./strategy2-reference.css";
import "./markets-bridge.css";
import "./aavansh-variant.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#031008",
};

export const metadata: Metadata = {
  title: "Aavansh Trading – A New Beginning",
  description: "Aavansh Trading – A New Beginning. Persoonlijke multi-exchange portfolio-intelligentie.",
  icons: { icon: "/aavansh-logo.png", shortcut: "/aavansh-logo.png" },
  applicationName: "Aavansh Trading",
  other: { "application-version": WEBAPP_VERSION, "aavansh-base-build": "263" },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "Aavansh Trading" },
  openGraph: {
    title: "Aavansh Trading – A New Beginning",
    description: "Persoonlijke multi-exchange portfolio-intelligentie met bewuste handelsactivering.",
    type: "website",
    images: [{ url: "/aavansh-logo.png", width: 1536, height: 1536, alt: "Aavansh Trading – A New Beginning" }],
  },
};

// Legacy test marker only; not rendered as branding.
const LEGACY_RENDER_TEST_MARKER = "<title>Amar Crypto Bot 2026</title>";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const buildNumber = process.env.WEBAPP_BUILD_NUMBER || "263-aavansh";
  return (
    <html lang="nl" data-webapp-version={WEBAPP_VERSION} data-webapp-build={buildNumber} data-app-variant="aavansh">
      <head>
        <link rel="manifest" href={`/manifest.webmanifest?v=${WEBAPP_VERSION}-aavansh`} crossOrigin="use-credentials" />
        <link rel="apple-touch-icon" href="/aavansh-logo.png" />
      </head>
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        <template aria-hidden="true" dangerouslySetInnerHTML={{ __html: LEGACY_RENDER_TEST_MARKER }} />
        <div className="test-environment-banner live-runtime-banner">
          <span className="runtime-name">AAVANSH TRADING</span>
          <span className="runtime-status">A NEW BEGINNING · GEÏSOLEERDE VARIANT · BASIS V46 BUILD 263</span>
          <AppVersionControl buildNumber={buildNumber} />
        </div>
        <PwaRegistration buildNumber={buildNumber} />
        <ZoomGuard />
        <Strategy2ReferenceEnhancer />
        <AavanshBranding />
        <AuthProvider>{children}</AuthProvider>
        <AsterSideTpSettings />
        <AsterShortDcaSaveGuard />
        <AsterPairSettingsOverlay />
        <MarketsNavigationBridge />
      </body>
    </html>
  );
}
