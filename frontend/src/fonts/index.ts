import localFont from "next/font/local";

/*
 * `adjustFontFallback` is left at its default so next/font emits a
 * size-adjusted Arial fallback for each face: the swap from fallback to real
 * font then keeps its line boxes, instead of reflowing the page under the
 * reader.
 */
export const quranFont = localFont({
  src: "./AmiriQuran-Regular.ttf",
  variable: "--font-quran",
  display: "swap",
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
  fallback: ["Tahoma", "Arial", "sans-serif"],
  preload: true,
});

/*
 * Landing-page brand faces (DESIGN.md, "Landing page — brand exception").
 * Imported only by src/app/page.tsx, so next/font preloads them on the
 * landing route alone — no cost on any other page.
 */
export const brandFont = localFont({
  src: "./ReemKufi-Variable.ttf",
  weight: "400 700",
  variable: "--font-brand",
  display: "swap",
  fallback: ["Tahoma", "Arial", "sans-serif"],
  preload: true,
});

export const amiriFont = localFont({
  src: "./Amiri-Regular.ttf",
  weight: "400",
  variable: "--font-amiri",
  display: "swap",
  fallback: ["Amiri", "serif"],
  preload: true,
});
