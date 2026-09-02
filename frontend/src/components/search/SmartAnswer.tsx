"use client";

import { Fragment } from "react";
import AyahInline from "./AyahInline";
import { useAyahTexts } from "./useAyahTexts";
import { ayahKey, ayahPlaceholders, parseAnswer } from "@/lib/smart-answer";
import type { SmartResponse } from "@/types/models";

interface SmartAnswerProps {
  response: SmartResponse;
  onCite: (n: number) => void;
}

export const GENERATED_BADGE = "إجابة مولّدة آليًا";

/**
 * The answer text with its citation chips and inline verses. Every `[n]`
 * becomes a chip that focuses citation card N; every `[[ayah:S:A]]` becomes
 * the canonical verse or nothing.
 */
export default function SmartAnswer({ response, onCite }: SmartAnswerProps) {
  const markdown = response.answer_md ?? "";
  const lookup = useAyahTexts(response.ayah_refs, ayahPlaceholders(markdown));
  if (markdown === "") return null;
  const paragraphs = parseAnswer(markdown, {
    citationCount: response.citations.length,
    ayahKeys: new Set(response.ayah_refs.map((item) => ayahKey(item.surah, item.ayah))),
  });

  return (
    <div className="smart-answer mt-4">
      <p className="mb-2 flex items-center gap-2 text-xs text-[var(--color-ink-muted)]">
        <span className="sp-badge">{GENERATED_BADGE}</span>
      </p>
      {/* A div, not a <p>: an inline verse is a <figure>, which a <p> cannot hold. */}
      {paragraphs.map((paragraph, index) => (
        <div key={index} className="smart-paragraph text-base leading-[1.9]">
          {paragraph.nodes.map((node, position) => {
            if (node.type === "text") return <Fragment key={position}>{node.text}</Fragment>;
            if (node.type === "cite") {
              return (
                <button
                  key={position}
                  type="button"
                  className="smart-cite-chip"
                  aria-controls={`cite-${node.n}`}
                  aria-label={`المرجع ${node.n}`}
                  onClick={() => onCite(node.n)}
                >
                  {node.n}
                </button>
              );
            }
            return <AyahInline key={position} ayah={lookup(node.surah, node.ayah)} />;
          })}
        </div>
      ))}
    </div>
  );
}
