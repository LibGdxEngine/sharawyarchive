"use client";

import { useState } from "react";
import { ApiError, postCorrectionForWords } from "@/lib/api";
import type { WordRange } from "@/lib/correction-selection";

interface CorrectionPanelProps {
  segmentId: number;
  range: WordRange;
  /** Transcript text under the range, used as the prefill and as the baseline. */
  originalText: string;
  onDismiss: () => void;
}

type Phase = "editing" | "sending" | "sent" | "failed";

const THANKS = "شكرًا، سيراجع الاقتراح قبل اعتماده";
const THROTTLED =
  "وصلنا عدد كبير من اقتراحاتك — جرّب مرة أخرى بعد ساعة، مع الشكر";
const UNAVAILABLE = "التصحيحات غير متاحة حاليًا";
const GENERIC = "تعذّر إرسال الاقتراح الآن. حاول مرة أخرى بعد قليل.";

function failureMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return THROTTLED;
    if (error.status === 404) return UNAVAILABLE;
  }
  return GENERIC;
}

/**
 * The inline correction form.
 *
 * Mounted under the transcript once a word range is selected. The parent keys
 * it by range, so choosing a different range gives a fresh, prefilled form
 * rather than carrying the previous edit over.
 */
export default function CorrectionPanel({
  segmentId,
  range,
  originalText,
  onDismiss,
}: CorrectionPanelProps) {
  const [text, setText] = useState(originalText);
  const [phase, setPhase] = useState<Phase>("editing");
  const [message, setMessage] = useState("");

  const suggestion = text.trim();
  const unchanged = suggestion === originalText.trim();

  const submit = async () => {
    setPhase("sending");
    try {
      await postCorrectionForWords(segmentId, range.start, range.end, suggestion);
      setPhase("sent");
      setMessage(THANKS);
    } catch (error) {
      setPhase("failed");
      setMessage(failureMessage(error));
    }
  };

  return (
    <section
      aria-label="اقتراح تصحيح"
      className="mt-4 border-t border-[var(--color-border)] pt-4"
    >
      <p className="text-xs text-[var(--color-ink-faint)]">
        النص الأصلي · الكلمات {range.start + 1}–{range.end + 1}
      </p>
      <p className="mt-1 text-sm leading-[1.8] text-[var(--color-ink-muted)]">
        {originalText}
      </p>

      {phase === "sent" ? (
        <p className="mt-3 text-sm text-[var(--color-ink)]">{message}</p>
      ) : (
        <>
          <label
            htmlFor="correction-text"
            className="mt-3 block text-xs text-[var(--color-ink-faint)]"
          >
            النص المقترح
          </label>
          <textarea
            id="correction-text"
            value={text}
            rows={2}
            onChange={(event) => setText(event.target.value)}
            className="mt-1 w-full resize-y border border-[var(--color-border)] bg-transparent p-2 text-base leading-[1.8] text-[var(--color-ink)]"
          />

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void submit()}
              disabled={
                phase === "sending" || suggestion.length === 0 || unchanged
              }
              className="rounded border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-ink)] disabled:opacity-50"
            >
              {phase === "sending" ? "جارٍ الإرسال…" : "إرسال الاقتراح"}
            </button>
            <button
              type="button"
              onClick={onDismiss}
              className="text-sm text-[var(--color-ink-muted)]"
            >
              إلغاء
            </button>
            {phase === "failed" ? (
              <span role="status" className="text-xs text-[var(--color-ink-muted)]">
                {message}
              </span>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}
