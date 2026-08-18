import type { Metadata, Viewport } from "next";
import { quranFont, uiFont } from "@/fonts";
import "./globals.css";
import GlobalAudio from "@/components/GlobalAudio";
import KeyboardShortcuts from "@/components/player/KeyboardShortcuts";
import PlayerBar from "@/components/player/PlayerBar";
import InstallPrompt from "@/components/InstallPrompt";
import ServiceWorkerRegistration from "@/components/ServiceWorkerRegistration";

export const viewport: Viewport = {
  themeColor: "#1a6b4a",
};

export const metadata: Metadata = {
  title: "أرشيف الشعراوي",
  description:
    "أرشيف صوتي قابل للبحث لخواطر الشيخ محمد متولي الشعراوي — ابحث عن أي عبارة وانتقل مباشرةً إلى لحظة قولها",
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
