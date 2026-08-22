"use client";

import { useEffect } from "react";

/**
 * Marks <body> while the verse page is mounted, so fixtures OUTSIDE the page
 * subtree — the fixed PlayerBar above all — pick up the gold token overrides
 * (`body[data-verse-theme]` in globals.css). The page content itself carries
 * `.verse-theme` server-side and never flashes; only the bar re-tints one
 * frame after hydration, which is the accepted trade-off.
 */
export default function VerseBodyTheme() {
  useEffect(() => {
    document.body.dataset.verseTheme = "";
    return () => {
      delete document.body.dataset.verseTheme;
    };
  }, []);

  return null;
}
