import type { Metadata, Viewport } from "next";
import { quranFont, uiFont } from "@/fonts";
import "./globals.css";
import GlobalAudio from "@/components/GlobalAudio";
import KeyboardShortcuts from "@/components/player/KeyboardShortcuts";
import PlayerBar from "@/components/player/PlayerBar";
import InstallPrompt from "@/components/InstallPrompt";
import ServiceWorkerRegistration from "@/components/ServiceWorkerRegistration";
import { SITE_NAME, SITE_URL } from "@/lib/site";

export const viewport: Viewport = {
  themeColor: "#1a6b4a",
};

const DESCRIPTION =
  "أرشيف صوتي قابل للبحث لخواطر الشيخ محمد متولي الشعراوي — ابحث عن أي عبارة وانتقل مباشرةً إلى لحظة قولها";

export const metadata: Metadata = {
  // Every route below resolves its relative canonical/OG urls against this.
  metadataBase: new URL(SITE_URL),
  title: SITE_NAME,
  description: DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    locale: "ar_AR",
    siteName: SITE_NAME,
    title: SITE_NAME,
    description: DESCRIPTION,
    url: "/",
  },
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "الشعراوي",
  },
  icons: {
    apple: "/icons/icon-192.png",
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      dir="rtl"
      lang="ar"
      data-scroll-behavior="smooth"
      className={`${quranFont.variable} ${uiFont.variable}`}
    >
      <body>
        {/*
          The audio element, the transport bar and the keyboard transport all
          live here, above the router outlet: route changes re-render
          {children} only, so navigating never interrupts playback.
        */}
        <GlobalAudio />
        <KeyboardShortcuts />
        {children}
        <PlayerBar />
        {/* PWA: service worker registration (production only) */}
        <ServiceWorkerRegistration />
        {/* PWA: add-to-home-screen prompt */}
        <InstallPrompt />
      </body>
    </html>
  );
}
