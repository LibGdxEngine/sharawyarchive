import type { Metadata } from "next";
import { quranFont, uiFont } from "@/fonts";
import "./globals.css";
import GlobalAudio from "@/components/GlobalAudio";

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
      className={`${quranFont.variable} ${uiFont.variable}`}
    >
      <body>
        <GlobalAudio />
        {children}
      </body>
    </html>
  );
}
