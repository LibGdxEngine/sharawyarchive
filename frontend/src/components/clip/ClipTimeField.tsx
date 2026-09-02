"use client";

import { useState } from "react";
import { formatMs, parseMs } from "@/lib/format";

interface ClipTimeFieldProps {
  label: string;
  valueMs: number;
  /** Commit a typed time. Rejected input never reaches here. */
  onCommit(ms: number): void;
}

/**
 * An `mm:ss` readout that is also an input.
 *
 * The composer's times used to be display-only, so the only way to reach a
 * moment was to drag for it. While the field has focus it keeps the reader's
 * literal text — half-typed input must not be snapped to a legal value under
 * their fingers — and commits on blur or Enter, whereupon the trim's own
 * word-snapping decides what the value really becomes.
 */
export default function ClipTimeField({
  label,
  valueMs,
  onCommit,
}: ClipTimeFieldProps) {
  const [draft, setDraft] = useState<string | null>(null);

  // Dropping the draft when the trim moves from elsewhere (a drag, a playhead
  // capture, a quick span) keeps the field showing the truth rather than a
  // stale edit. Adjusted during render rather than in an effect: an effect
  // would paint the old text first and then re-render over it.
  const [lastValueMs, setLastValueMs] = useState(valueMs);
  if (lastValueMs !== valueMs) {
    setLastValueMs(valueMs);
    setDraft(null);
  }

  const text = draft ?? formatMs(valueMs);
  const invalid = draft !== null && parseMs(draft) === null;

  const commit = (): void => {
    if (draft === null) return;
    const ms = parseMs(draft);
    setDraft(null);
    if (ms !== null) onCommit(ms);
  };

  return (
    <label className="flex items-center gap-2 text-xs text-[var(--color-ink-muted)]">
      {label}
      <input
        type="text"
        inputMode="numeric"
        dir="ltr"
        value={text}
        aria-invalid={invalid}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Escape") {
            event.preventDefault();
            setDraft(null);
          }
        }}
        className="w-20 rounded border px-2 py-1.5 text-center tabular-nums text-[var(--color-ink)]"
        // The palette has no danger colour and the site does not do error
        // theatre (see ErrorNote): an unreadable value simply darkens its
        // border and, on commit, is discarded rather than applied.
        style={{
          borderColor: invalid ? "var(--color-ink)" : "var(--color-border)",
        }}
      />
    </label>
  );
}
