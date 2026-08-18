"use client";

import { useEffect, useState } from "react";
import ChunkResultList from "@/components/ChunkResultList";
import { getRelated } from "@/lib/api";
import type { SearchChunkResult } from "@/types/models";

interface RelatedPassagesProps {
  segmentId: number;
}

/**
 * Passages near this one in embedding space, under the transcript.
 *
 * A suggestion, not a promise: nothing announces it before the answer arrives,
 * and an empty list or a failed request leaves the page exactly as it was. It
 * is also skipped outright while offline, where the request cannot succeed and
 * the saved segment is the whole point of being here.
 */
export default function RelatedPassages({ segmentId }: RelatedPassagesProps) {
  const [related, setRelated] = useState<SearchChunkResult[]>([]);

  useEffect(() => {
    if (typeof navigator !== "undefined" && navigator.onLine === false) return;

    let cancelled = false;
    void (async () => {
      try {
        const results = await getRelated(segmentId);
        if (!cancelled) setRelated(results);
      } catch {
        // Quiet by design — a related-passages rail is never worth an error.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [segmentId]);

  if (related.length === 0) return null;

  return (
    <section className="mt-10 border-t border-[var(--color-border-subtle)] pt-6">
      <h2 className="text-xs text-[var(--color-ink-muted)]">مقاطع ذات صلة</h2>
      <ChunkResultList results={related} emptyLabel="" />
    </section>
  );
}
