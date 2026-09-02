"use client";

import Link from "next/link";
import { formatMs } from "@/lib/format";
import type { SmartCitation } from "@/types/models";

export const MACHINE_BADGE = "نص آلي";

interface CitationCardProps {
  citation: SmartCitation;
  active: boolean;
  pending: boolean;
  failed: boolean;
  onPlay: (citation: SmartCitation) => void;
}

export function placeLine(item: {
  surah: number | null;
  ayah_start: number | null;
  ayah_end: number | null;
}): string {
  const parts: string[] = [];
  if (item.surah !== null) parts.push(`سورة ${item.surah}`);
  if (item.ayah_start !== null && item.ayah_end !== null) {
    parts.push(
      item.ayah_start === item.ayah_end
        ? `الآية ${item.ayah_start}`
        : `الآيات ${item.ayah_start}–${item.ayah_end}`
    );
  }
  return parts.join(" · ");
}

/**
 * One verified quote: the words the recogniser heard, at the milliseconds
 * where it heard them. `id="cite-N"` is what the answer's chips point at, and
 * `tabIndex={-1}` lets a chip move focus here without adding a tab stop.
 */
export default function CitationCard({ citation, active, pending, failed, onPlay }: CitationCardProps) {
  const place = placeLine(citation);
  return (
    <article
      id={`cite-${citation.n}`}
      tabIndex={-1}
      data-active={active ? "true" : undefined}
      className="smart-cite-card"
    >
      <p className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-ink-muted)]">
        <span className="smart-cite-number">{citation.n}</span>
        <span className="truncate">{citation.segment_title}</span>
        {place ? <span>· {place}</span> : null}
        <span>· {formatMs(citation.start_ms)}</span>
        <span className="sp-badge">{MACHINE_BADGE}</span>
      </p>
      <blockquote className="mt-1 text-base leading-[1.8]">«{citation.quote_display}»</blockquote>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onPlay(citation)}
          disabled={pending}
          className="chunk-chip"
        >
          {pending ? "جارٍ التحميل…" : "تشغيل من هنا"}
        </button>
        <Link href={citation.listen_url} className="text-xs underline-offset-4 hover:underline">
          الاستماع في سياقه
        </Link>
        {failed ? (
          <span className="text-xs text-[var(--color-ink-muted)]">تعذّر تشغيل المقطع الآن.</span>
        ) : null}
      </div>
    </article>
  );
}
