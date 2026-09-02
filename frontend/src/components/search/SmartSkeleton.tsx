import { STAGE_MESSAGES } from "./useSmartSearch";

interface SmartSkeletonProps {
  stage: 0 | 1 | 2;
  slow: boolean;
}

/** Ghost blocks plus the one line of honest status while the answer is written. */
export default function SmartSkeleton({ stage, slow }: SmartSkeletonProps) {
  return (
    <div className="smart-skeleton mt-6" aria-busy="true">
      <p role="status" aria-live="polite" className="text-sm text-[var(--color-ink-muted)]">
        {STAGE_MESSAGES[stage]}
        {slow ? " يستغرق هذا وقتًا أطول من المعتاد…" : null}
      </p>
      <div className="mt-4 animate-pulse space-y-3">
        <div className="h-4 w-11/12 rounded bg-[var(--color-bg-subtle)]" />
        <div className="h-4 w-9/12 rounded bg-[var(--color-bg-subtle)]" />
        <div className="h-4 w-10/12 rounded bg-[var(--color-bg-subtle)]" />
        <div className="mt-6 h-20 rounded-2xl bg-[var(--color-bg-subtle)]" />
        <div className="h-20 rounded-2xl bg-[var(--color-bg-subtle)]" />
      </div>
    </div>
  );
}
