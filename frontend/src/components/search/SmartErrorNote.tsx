"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { searchHref, type SearchKindParam } from "@/lib/search-mode";
import type { SmartErrorKind } from "@/lib/smart-transport";

interface SmartErrorNoteProps {
  error: SmartErrorKind;
  retryAfter: number | null;
  query: string;
  kind: SearchKindParam;
}

export const ERROR_COPY: Record<SmartErrorKind, string> = {
  rate_limited: "وصلت إلى الحد المسموح من الأسئلة في هذه الساعة.",
  unavailable: "البحث الذكي غير متاح حاليًا. يمكنك استخدام البحث الدقيق.",
  invalid: "تعذّر فهم السؤال. جرّب صياغة أقصر وأوضح.",
  timeout: "استغرقت الإجابة وقتًا أطول من المعتاد ولم تكتمل. حاول مرة أخرى.",
  network: "تعذّر الوصول إلى الأرشيف الآن. حاول مرة أخرى بعد قليل.",
};

/**
 * The quiet failure line, with a countdown when the API said how long to
 * wait. Mount it with `key={retryAfter}`: the countdown starts from the prop
 * once, on mount, and only ticks from there.
 */
export default function SmartErrorNote({ error, retryAfter, query, kind }: SmartErrorNoteProps) {
  const [secondsLeft, setSecondsLeft] = useState(retryAfter ?? 0);

  useEffect(() => {
    if (retryAfter === null || retryAfter <= 0) return;
    const timer = setInterval(() => {
      setSecondsLeft((previous) => (previous <= 1 ? 0 : previous - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [retryAfter]);

  return (
    <div className="py-8 text-sm text-[var(--color-ink-muted)]" role="alert">
      <p>
        {ERROR_COPY[error]}
        {error === "rate_limited" && secondsLeft > 0 ? (
          <span className="ms-1" data-testid="retry-countdown">
            يمكنك المحاولة بعد {secondsLeft} ثانية.
          </span>
        ) : null}
      </p>
      <Link href={searchHref(query, kind, "exact")} className="mt-2 inline-block underline underline-offset-4">
        تابع بالبحث الدقيق
      </Link>
    </div>
  );
}
