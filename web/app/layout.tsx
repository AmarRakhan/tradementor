import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AuthProvider } from "@/components/auth-provider";
import { PwaRegistration } from "@/components/pwa-registration";
import { ZoomGuard } from "@/components/zoom-guard";
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
  title: "TradeMentor Web",
  description: "Eén veilige trade floor voor Hyperliquid, Aster en je totale portfolio.",
  icons: { icon: "/tradementor-logo.png?v=redgreen-1", shortcut: "/tradementor-logo.png?v=redgreen-1" },
  manifest: "/manifest.webmanifest",
  applicationName: "TradeMentor",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "TradeMentor" },
  openGraph: {
    title: "TradeMentor Web",
    description: "Persoonlijke multi-exchange portfolio-intelligentie met bewuste handelsactivering.",
    type: "website",
    images: [{ url: "/tradementor-social.png", width: 1672, height: 941, alt: "TradeMentor portfolio control room" }],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="nl"><body className={`${geistSans.variable} ${geistMono.variable}`}><PwaRegistration /><ZoomGuard /><AuthProvider>{children}</AuthProvider></body></html>;
}
