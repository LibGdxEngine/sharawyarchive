"use client";

import { formatMs } from "@/lib/format";
import type { TrimHandleName } from "./useTrimHandles";
import type { TranscriptWord } from "@/types/models";

interface TrimHandleProps {
  handle: TrimHandleName;
  words: readonly TranscriptWord[];
  /** Word index this handle sits on. */
  at: number;
  /** The other handle's word index — the bound this one may not cross. */
  opposite: number;
  dragging: boolean;
  /** Spread of {@link useTrimHandles}' `handleProps`. */
  pointer: React.ComponentPropsWithoutRef<"button">;
}

const LABEL: Record<TrimHandleName, string> = {
  start: "بداية المقطع",
  end: "نهاية المقطع",
};

/**
 * One end of the trim, grabbable by finger, mouse or keyboard.
 *
 * Drawn as a grip rather than a `[` / `]` character. Brackets are mirrored by
 * the bidi algorithm, which is why the old handles carried a `dir="ltr"`
 * override — a per-component RTL hack of exactly the kind CLAUDE.md rule 3
 * forbids. A glyph with no directionality needs no override, and gives the
 * 44px target a bracket in body text never could.
 */
export default function TrimHandle({
  handle,
  words,
  at,
  opposite,
  dragging,
  pointer,
}: TrimHandleProps) {
  // The legal bounds, not the whole transcript: a screen reader announcing
  // "1 of 8986" while the handle can only reach word 40 is announcing fiction.
  const min = handle === "start" ? 0 : opposite;
  const max = handle === "start" ? opposite : words.length - 1;

  return (
    <button
      type="button"
      role="slider"
      aria-label={LABEL[handle]}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={at}
      aria-valuetext={`${words[at].t} · ${formatMs(
        handle === "start" ? words[at].s : words[at].e
      )}`}
      {...pointer}
      className={`mx-0.5 inline-flex h-11 w-7 shrink-0 cursor-ew-resize touch-none items-center justify-center rounded-md align-middle transition-colors ${
        dragging
          ? "bg-[var(--color-ink)] text-[var(--color-surface)]"
          : "bg-[var(--color-accent)] text-[var(--color-surface)]"
      }`}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 12 24"
        className="h-5 w-3"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.6}
        strokeLinecap="round"
      >
        <line x1="4" y1="3" x2="4" y2="21" />
        <line x1="8" y1="3" x2="8" y2="21" />
      </svg>
    </button>
  );
}
