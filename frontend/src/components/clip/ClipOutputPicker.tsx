"use client";

import ClipChoice from "./ClipChoice";
import type { ClipOutput } from "@/types/models";

const OPTIONS: readonly { id: ClipOutput; label: string; note: string }[] = [
  { id: "video", label: "فيديو", note: "بطاقة رأسية بالكلمات" },
  { id: "audio", label: "صوت فقط", note: "بلا حدّ لطول المقطع" },
];

/** "الصيغة" — what the render job produces. */
export default function ClipOutputPicker({
  output,
  setOutput,
  accent,
}: {
  output: ClipOutput;
  setOutput(next: ClipOutput): void;
  accent?: string;
}) {
  return (
    <fieldset>
      <legend className="text-xs text-[var(--color-ink-faint)]">الصيغة</legend>
      <div className="mt-2 flex flex-wrap gap-3">
        {OPTIONS.map((option) => (
          <ClipChoice
            key={option.id}
            selected={option.id === output}
            accent={accent}
            onClick={() => setOutput(option.id)}
          >
            <span>{option.label}</span>
            <span className="text-[var(--color-ink-faint)]">{option.note}</span>
          </ClipChoice>
        ))}
      </div>
    </fieldset>
  );
}
