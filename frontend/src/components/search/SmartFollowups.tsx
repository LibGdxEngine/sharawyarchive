"use client";

import { useRouter } from "next/navigation";
import { searchHref, type SearchKindParam } from "@/lib/search-mode";

interface SmartFollowupsProps {
  followups: string[];
  kind: SearchKindParam;
}

/** The generator's suggested next questions, each a smart search of its own. */
export default function SmartFollowups({ followups, kind }: SmartFollowupsProps) {
  const router = useRouter();
  if (followups.length === 0) return null;
  return (
    <section className="mt-8">
      <h2 className="text-xs text-[var(--color-ink-muted)]">أسئلة قريبة</h2>
      <ul className="mt-2 flex flex-wrap gap-2">
        {followups.map((question) => (
          <li key={question}>
            <button
              type="button"
              className="chunk-chip"
              onClick={() => router.push(searchHref(question, kind, "smart"))}
            >
              {question}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
