"use client";

import { useState } from "react";
import SearchAutocomplete, { type SearchKind } from "./SearchAutocomplete";
import { useSearchMode } from "@/components/search/useSearchMode";

const EXAMPLES: { glyph: string; glyphClass: string; label: string }[] = [
  {
    glyph: "﴾",
    glyphClass: "[font-family:var(--font-amiri)] text-[17px] leading-none",
    label: "وما تشاءون إلا أن يشاء الله",
  },
  {
    glyph: "#",
    glyphClass: "text-sm font-bold leading-none",
    label: "الرزق والتوكل",
  },
  {
    glyph: "۞",
    glyphClass: "text-base leading-none",
    label: "سورة التكوير",
  },
  {
    glyph: "❞",
    glyphClass: "[font-family:var(--font-amiri)] text-base leading-none",
    label: "الصبر عند الصدمة الأولى",
  },
  {
    glyph: "۞",
    glyphClass: "text-base leading-none",
    label: "سورة الرحمن",
  },
];

/**
 * The search hero as one client island: the autocomplete input plus the
 * recommendation chips that fill it. Clicking a recommendation writes the
 * text into the input and focuses it — the recommendation flows through the
 * search box, where it can be filtered by kind and refined before submitting.
 */
export default function SearchHero() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<SearchKind>("all");
  const [mode, setMode] = useSearchMode();

  const fillRecommendation = (label: string) => {
    setQuery(label);
    const input = document.getElementById("site-search");
    if (input instanceof HTMLInputElement) {
      input.focus();
      input.select();
    }
  };

  return (
    <div className="w-full">
      <SearchAutocomplete
        value={query}
        onChange={setQuery}
        kind={kind}
        onKindChange={setKind}
        mode={mode}
        onModeChange={setMode}
      />

      <div className="mt-4 flex flex-col items-center gap-2">
        <span className="text-xs font-medium text-[var(--landing-ink-4)]">
          أجرّب البحث عن…
        </span>
        <ul className="flex flex-wrap justify-center gap-2">
          {EXAMPLES.map(({ glyph, glyphClass, label }) => (
            <li key={label}>
              <button
                type="button"
                onClick={() => fillRecommendation(label)}
                aria-label={`املأ البحث بـ: ${label}`}
                className="flex items-center gap-2 rounded-full border border-[var(--landing-chip-border)] bg-[var(--landing-chip-bg)] px-4 py-1.5 text-sm text-[var(--landing-ink-3)] transition-colors hover:border-[var(--landing-gold-focus)] hover:text-[var(--landing-chip-ink-hover)]"
              >
                <span
                  aria-hidden
                  className={`text-[var(--landing-gold)] ${glyphClass}`}
                >
                  {glyph}
                </span>
                {label}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
