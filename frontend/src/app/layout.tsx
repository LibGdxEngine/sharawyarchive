import type { Metadata } from "next";
import { quranFont, uiFont } from "@/fonts";
import "./globals.css";
import GlobalAudio from "@/components/GlobalAudio";
import KeyboardShortcuts from "@/components/player/KeyboardShortcuts";
import PlayerBar from "@/components/player/PlayerBar";

export const metadata: Metadata = {
  title: "أرشيف الشعراوي",
  description:
    "أرشيف صوتي قابل للبحث لخواطر الشيخ محمد متولي الشعراوي — ابحث عن أي عبارة وانتقل مباشرةً إلى لحظة قولها",
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
      </body>
    </html>
  );
}
