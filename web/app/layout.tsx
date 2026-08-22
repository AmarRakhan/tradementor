import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AuthProvider } from "@/components/auth-provider";
import { PwaRegistration } from "@/components/pwa-registration";
import { ZoomGuard } from "@/components/zoom-guard";
import { AppVersionControl } from "@/components/app-version-control";
import { WEBAPP_VERSION } from "@/lib/app-version";
import "./globals.css";
import "./premium.css";
import "./premium-next.css";
import "./suriname-heritage.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#03060d",
};

export const metadata: Metadata = {
  title: "Amar Crypto Bot 2026",
  description: "Eén veilige trade floor voor Hyperliquid, Aster en je totale portfolio.",
  icons: { icon: "/tradementor-logo.png?v=redgreen-1", shortcut: "/tradementor-logo.png?v=redgreen-1" },
  applicationName: "Amar Crypto Bot 2026",
  other: { "application-version": WEBAPP_VERSION },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "Amar Bot 2026" },
  openGraph: {
    title: "TradeMentor Web",
    description: "Persoonlijke multi-exchange portfolio-intelligentie met bewuste handelsactivering.",
    type: "website",
    images: [{ url: "/tradementor-social.png", width: 1672, height: 941, alt: "TradeMentor portfolio control room" }],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const buildNumber = process.env.WEBAPP_BUILD_NUMBER || "local";
  return (
    <html lang="nl" data-webapp-version={WEBAPP_VERSION} data-webapp-build={buildNumber}>
      <head>
        <link rel="manifest" href={`/manifest.webmanifest?v=${WEBAPP_VERSION}`} crossOrigin="use-credentials" />
        <link rel="apple-touch-icon" href="/tradementor-icon-192.png" />
      </head>
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        <div className="test-environment-banner live-runtime-banner">
          <span className="runtime-name">AMAR CRYPTO BOT 2026</span>
          <span className="runtime-status">PLATFORMSTATUS · STRATEGY 2-RUNTIME · DIT IS NIET JOUW ACCOUNTSTATUS</span>
          <AppVersionControl buildNumber={buildNumber} />
        </div>
        <PwaRegistration buildNumber={buildNumber} />
        <ZoomGuard />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
