import localFont from "next/font/local";

export const quranFont = localFont({
  src: "./AmiriQuran-Regular.ttf",
  variable: "--font-quran",
  display: "swap",
  adjustFontFallback: false,
  fallback: ["Amiri", "serif"],
  preload: true,
});

export const uiFont = localFont({
  src: [
    {
      path: "./IBMPlexSansArabic-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "./IBMPlexSansArabic-Medium.ttf",
      weight: "500",
      style: "normal",
    },
    {
      path: "./IBMPlexSansArabic-SemiBold.ttf",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-ui",
  display: "swap",
  adjustFontFallback: false,
  fallback: ["Tahoma", "Arial", "sans-serif"],
  preload: true,
});
