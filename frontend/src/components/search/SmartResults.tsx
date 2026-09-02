"use client";

import { useState } from "react";
import CitationCard from "./CitationCard";
import PassageList from "./PassageList";
import SmartAnswer from "./SmartAnswer";
import SmartDisclaimer from "./SmartDisclaimer";
import SmartErrorNote from "./SmartErrorNote";
import SmartFeedback from "./SmartFeedback";
import SmartFollowups from "./SmartFollowups";
import SmartSkeleton from "./SmartSkeleton";
import SmartStatusBanner from "./SmartStatusBanner";
import { useSmartSearch } from "./useSmartSearch";
import { usePlaySegmentAt } from "@/components/player/usePlaySegmentAt";
import { usePrefersReducedMotion } from "@/components/player/useActiveWord";
import type { SearchKindParam } from "@/lib/search-mode";
import type { SmartTransport } from "@/lib/smart-transport";
import type { SmartCitation, SmartPassage } from "@/types/models";

interface SmartResultsProps {
  question: string;
  kind: SearchKindParam;
  debug?: boolean;
  /** Test seam; the fetch transport by default. */
  transport?: SmartTransport;
}

/**
 * The smart-mode island. Mount it with `key={question}` so a new question is
 * a fresh component: state, focus and playback status start over.
 */
export default function SmartResults({ question, kind, debug = false, transport }: SmartResultsProps) {
  const state = useSmartSearch(question, { debug, transport });
  const reducedMotion = usePrefersReducedMotion();
  const { play, pendingKey, failedKey } = usePlaySegmentAt();
  const [activeCite, setActiveCite] = useState<number | null>(null);

  const focusCitation = (n: number) => {
    setActiveCite(n);
    const card = document.getElementById(`cite-${n}`);
    if (card === null) return;
    card.scrollIntoView?.({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
    card.focus({ preventScroll: true });
  };
  const playCitation = (citation: SmartCitation) =>
    void play(`cite-${citation.n}`, citation.segment_id, citation.start_ms);
  const playPassage = (passage: SmartPassage) =>
    void play(`passage-${passage.passage_id}`, passage.segment_id, passage.start_ms);

  if (state.phase === "loading" || state.phase === "idle") {
    return <SmartSkeleton stage={state.stage} slow={state.slow} />;
  }
  if (state.phase === "error" || state.response === null) {
    return (
      <SmartErrorNote
        key={String(state.retryAfter)}
        error={state.error ?? "network"}
        retryAfter={state.retryAfter}
        query={question}
        kind={kind}
      />
    );
  }

  const { response } = state;
  return (
    <div className="smart-results">
      <SmartStatusBanner status={response.status} />
      <SmartAnswer response={response} onCite={focusCitation} />
      {response.citations.length > 0 ? (
        <section className="mt-6">
          <h2 className="text-xs text-[var(--color-ink-muted)]">المراجع</h2>
          <div className="mt-2 space-y-2">
            {response.citations.map((citation) => (
              <CitationCard
                key={citation.n}
                citation={citation}
                active={activeCite === citation.n}
                pending={pendingKey === `cite-${citation.n}`}
                failed={failedKey === `cite-${citation.n}`}
                onPlay={playCitation}
              />
            ))}
          </div>
        </section>
      ) : null}
      <PassageList
        passages={response.passages}
        pendingKey={pendingKey}
        failedKey={failedKey}
        onPlay={playPassage}
      />
      <SmartFollowups followups={response.followups} kind={kind} />
      {response.status !== "degraded" ? <SmartFeedback queryId={response.query_id} /> : null}
      <SmartDisclaimer />
      {debug && response.debug ? (
        <details className="mt-6 text-xs">
          <summary className="cursor-pointer text-[var(--color-ink-muted)]">debug</summary>
          <pre dir="ltr" className="mt-2 overflow-x-auto rounded bg-[var(--color-bg-subtle)] p-3 text-start">
            {JSON.stringify(response.debug, null, 2)}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
