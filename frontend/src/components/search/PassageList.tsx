"use client";

import Link from "next/link";
import { MACHINE_BADGE, placeLine } from "./CitationCard";
import { MACHINE_TRANSCRIPT_NOTE } from "@/components/ChunkResultList";
import { formatMs } from "@/lib/format";
import type { SmartPassage } from "@/types/models";

interface PassageListProps {
  passages: SmartPassage[];
  pendingKey: string | number | null;
  failedKey: string | number | null;
  onPlay: (passage: SmartPassage) => void;
}

/**
 * The passages the answer was written from — always shown, answer or not,
 * because they are the archive itself: a degraded response still lets the
 * reader listen.
 */
export default function PassageList({ passages, pendingKey, failedKey, onPlay }: PassageListProps) {
  if (passages.length === 0) return null;
  return (
    <section className="mt-8">
      <h2 className="flex items-center gap-2 text-xs text-[var(--color-ink-muted)]">
        المقاطع التي اعتمدت عليها الإجابة
        <span className="sp-badge">{MACHINE_BADGE}</span>
      </h2>
      <p className="pt-2 text-xs leading-relaxed text-[var(--color-ink-muted)]">
        {MACHINE_TRANSCRIPT_NOTE}
      </p>
      <ul className="space-y-1">
        {passages.map((passage, index) => {
          const key = `passage-${passage.passage_id}`;
          const place = placeLine(passage);
          return (
            <li
              key={passage.passage_id}
              className="chunk-row"
              style={{ animationDelay: `${Math.min(index, 10) * 45}ms` }}
            >
              <p className="text-xs text-[var(--color-ink-muted)]">
                {passage.segment_title}
                {place ? ` · ${place}` : ""} · {formatMs(passage.start_ms)}
              </p>
              <Link
                href={`/listen/${passage.segment_id}?t=${passage.start_ms}`}
                className="mt-1 block text-base leading-[1.8] underline-offset-4 decoration-[var(--color-border)] hover:underline"
              >
                {passage.excerpt_display}
              </Link>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => onPlay(passage)}
                  disabled={pendingKey === key}
                  className="chunk-chip"
                >
                  {pendingKey === key ? "جارٍ التحميل…" : "تشغيل من هنا"}
                </button>
                {failedKey === key ? (
                  <span className="text-xs text-[var(--color-ink-muted)]">تعذّر تشغيل المقطع الآن.</span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
