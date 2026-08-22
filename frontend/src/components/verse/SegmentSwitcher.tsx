"use client";

import { formatMs, kindLabel } from "@/lib/format";
import type { SegmentSummary } from "@/types/models";

interface SegmentSwitcherProps {
  segments: SegmentSummary[];
  currentId: number;
  onSelect(id: number): void;
}

/**
 * The other segments covering this verse — episodes and recitations. The
 * current one is a pressed pill; picking another swaps the player without
 * leaving the page (the id lands in `?seg=` so the URL stays shareable).
 */
export default function SegmentSwitcher({
  segments,
  currentId,
  onSelect,
}: SegmentSwitcherProps) {
  if (segments.length < 2) return null;

  return (
    <nav aria-label="مقاطع أخرى تغطي هذه الآية" className="mt-5">
      <p className="text-xs text-[var(--color-ink-faint)]">
        مقاطع تغطي هذه الآية
      </p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {segments.map((segment) => {
          const isCurrent = segment.id === currentId;
          return (
            <li key={segment.id}>
              <button
                type="button"
                aria-pressed={isCurrent}
                onClick={() => {
                  if (!isCurrent) onSelect(segment.id);
                }}
                className={`max-w-72 rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
                  isCurrent
                    ? "border-[var(--verse-gold)] bg-[var(--verse-badge-bg)] text-[var(--verse-deep)]"
                    : "border-[var(--color-border)] text-[var(--color-ink-muted)] hover:border-[var(--verse-gold)]"
                }`}
              >
                <span className="font-semibold">{kindLabel(segment.kind)}</span>
                <span className="mx-1.5 truncate">{segment.title}</span>
                <span dir="ltr" className="tabular-nums text-[var(--color-ink-faint)]">
                  {formatMs(segment.duration_ms)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
