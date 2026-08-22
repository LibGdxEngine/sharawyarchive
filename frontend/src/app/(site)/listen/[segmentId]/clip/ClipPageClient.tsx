"use client";

import Link from "next/link";
import ErrorNote from "@/components/ErrorNote";
import ClipComposer from "@/components/player/ClipComposer";
import { useSegmentData } from "@/components/player/useSegmentData";
import { kindLabel } from "@/lib/format";

interface ClipPageClientProps {
  segmentId: number;
}

/**
 * Data shell for /listen/[segmentId]/clip.
 *
 * Same fetch as the listen page itself (browser-side, offline-first): the
 * segment and transcript are loaded here and handed to the full-page clip
 * composer.
 */
export default function ClipPageClient({ segmentId }: ClipPageClientProps) {
  const data = useSegmentData(segmentId);

  if (data.status === "loading") {
    return (
      <div
        role="status"
        aria-label="جارٍ تحميل المقطع"
        className="animate-pulse"
      >
        <span className="sr-only">جارٍ تحميل المقطع…</span>
        <div aria-hidden>
          <div className="h-3 w-40 rounded bg-[var(--color-bg-subtle)]" />
          <div className="mt-2 h-7 w-2/3 rounded bg-[var(--color-bg-subtle)]" />
          <div className="mt-6 h-40 rounded border border-[var(--lp-card-border)] bg-[var(--color-bg-subtle)]" />
        </div>
      </div>
    );
  }

  if (data.status === "error") {
    return (
      <ErrorNote>تعذّر تحميل هذا المقطع الآن. حاول مرة أخرى بعد قليل.</ErrorNote>
    );
  }

  const { segment, transcript } = data;

  return (
    <div>
      <p className="listen-kicker">
        <Link
          href={`/listen/${segment.id}`}
          className="underline-offset-4 hover:underline"
        >
          العودة إلى الاستماع
        </Link>
      </p>
      <h1 className="listen-title [font-family:var(--font-amiri)]">
        {segment.title}
      </h1>
      <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
        {kindLabel(segment.kind)} · مقطع للمشاركة
      </p>

      {transcript === null ? (
        <p className="mt-6 rounded border border-[var(--lp-card-border)] bg-[var(--lp-card)] p-4 text-sm leading-relaxed text-[var(--color-ink-muted)]">
          لم يُفرَّغ هذا المقطع بعد — تظهر أداة الاقتطاع فور اكتمال التفريغ
          الآلي.
        </p>
      ) : (
        <ClipComposer segment={segment} />
      )}
    </div>
  );
}
