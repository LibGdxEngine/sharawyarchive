"use client";

import { siteHost } from "@/lib/site";
import type { WordTrim } from "@/lib/word-trim";
import type { TranscriptWord } from "@/types/models";

/** One visual theme of the 9:16 preview (mockup: كلاسيكي / عصري / تركيز). */
export interface ClipTheme {
  id: "classic" | "modern" | "focus";
  label: string;
  /** CSS background of the frame (color or gradient). */
  background: string;
  text: string;
  /** Ayah words keep a distinct color in EVERY theme (rule 1 visibility). */
  quran: string;
  highlight: string;
  highlightText: string;
  /** Swatch chip colors for the picker. */
  swatchBg: string;
  swatchInk: string;
}

export const CLIP_THEMES: readonly ClipTheme[] = [
  {
    id: "classic",
    label: "كلاسيكي",
    background: "#12352b",
    text: "#f2e8d2",
    quran: "#c9a45c",
    highlight: "#c9a45c",
    highlightText: "#132a22",
    swatchBg: "#12352b",
    swatchInk: "#c9a45c",
  },
  {
    id: "modern",
    label: "عصري",
    background: "#000000",
    text: "#ffffff",
    quran: "#c9a45c",
    highlight: "#ffd84d",
    highlightText: "#111111",
    swatchBg: "#000000",
    swatchInk: "#ffd84d",
  },
  {
    id: "focus",
    label: "تركيز",
    background: "linear-gradient(135deg, #8a6b2f, #3a2e14)",
    text: "#ffffff",
    quran: "#ead9ac",
    highlight: "rgba(255, 255, 255, 0.95)",
    highlightText: "#1a1508",
    swatchBg: "linear-gradient(135deg, #8a6b2f, #3a2e14)",
    swatchInk: "#ffffff",
  },
];

/**
 * Which server render preset each preview theme stands for. The backend's
 * presets predate this page and renaming them costs a migration against the
 * (segment, range, preset) uniqueness for zero user value — so the mapping is
 * by visual proximity to `backend/clips/subtitles.py` PRESETS: `night` is the
 * dark green, `classic` the dark warm/amber, `light` the paper one.
 */
export const CLIP_THEME_PRESET: Record<ClipTheme["id"], string> = {
  classic: "night",
  modern: "classic",
  focus: "light",
};

interface ClipPreviewProps {
  words: TranscriptWord[];
  trim: WordTrim;
  theme: ClipTheme;
  /** Transcript positions that belong to a located ayah recitation. */
  isQuranWord(index: number): boolean;
  /** Live transcript word index (-1 when idle). */
  activeWordIndex: number;
}

/**
 * The 9:16 phone-frame preview of the clip: the trimmed words in the chosen
 * theme, the word being spoken highlighted, progress + attribution at the
 * bottom — a faithful stand-in for what the rendered MP4 will look like.
 */
export default function ClipPreview({
  words,
  trim,
  theme,
  isQuranWord,
  activeWordIndex,
}: ClipPreviewProps) {
  const startMs = words[trim.startWord].s;
  const endMs = words[trim.endWord].e;
  const inTrim =
    activeWordIndex >= trim.startWord && activeWordIndex <= trim.endWord;
  const progress = inTrim
    ? Math.min(
        100,
        Math.round(((words[activeWordIndex].s - startMs) / (endMs - startMs)) * 100)
      )
    : 0;

  return (
    <div
      aria-hidden="true"
      className="relative flex h-[444px] w-[250px] shrink-0 flex-col items-center justify-center overflow-hidden rounded-[18px] border border-[var(--color-border)] px-4 py-6"
      style={{ background: theme.background }}
    >
      <p className="max-h-[330px] overflow-hidden text-center text-[17px] leading-[2.3]">
        {words.slice(trim.startWord, trim.endWord + 1).map((word, offset) => {
          const index = trim.startWord + offset;
          const quran = isQuranWord(index);
          const active = index === activeWordIndex;
          return (
            <span key={word.i}>
              <span
                className="rounded px-0.5"
                style={{
                  fontFamily: quran ? "var(--font-quran)" : undefined,
                  color: active
                    ? theme.highlightText
                    : quran
                      ? theme.quran
                      : theme.text,
                  backgroundColor: active ? theme.highlight : undefined,
                }}
              >
                {word.t}
              </span>{" "}
            </span>
          );
        })}
      </p>

      <div className="absolute inset-x-0 bottom-4 flex flex-col items-center gap-2">
        <div className="relative h-[3px] w-2/3 rounded bg-white/25">
          <span
            className="absolute top-0 h-[3px] rounded bg-[#c9a45c]"
            style={{ insetInlineStart: 0, width: `${progress}%` }}
          />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="flex h-3.5 items-end gap-px" aria-hidden="true">
            <span className="h-1 w-[2.5px] rounded bg-[#c9a45c]" />
            <span className="h-2 w-[2.5px] rounded bg-[#c9a45c]" />
            <span className="h-3.5 w-[2.5px] rounded bg-[#c9a45c]" />
            <span className="h-2 w-[2.5px] rounded bg-[#c9a45c]" />
            <span className="h-1 w-[2.5px] rounded bg-[#c9a45c]" />
          </span>
          <span className="text-[10px] text-white/85">
            أرشيف الشعراوي · {siteHost()}
          </span>
        </div>
      </div>
    </div>
  );
}
