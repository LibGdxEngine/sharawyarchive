/*
 * Skeleton for /search: the route is force-dynamic and waits on the search
 * API, so client-side navigations would otherwise show nothing at all.
 * Ghost blocks only — no text that could contradict the real results.
 * The global prefers-reduced-motion kill-switch neutralises animate-pulse.
 */
export default function Loading() {
  return (
    <main className="search-page reading-column page-shell pt-8">
      <div className="animate-pulse">
        <div className="h-6 w-2/3 rounded-lg bg-[var(--color-bg-subtle)]" />
        <div className="mt-3 h-3 w-40 rounded bg-[var(--color-bg-subtle)]" />
        <div className="mt-10 space-y-4">
          <div className="h-24 rounded-2xl bg-[var(--color-bg-subtle)]" />
          <div className="h-24 rounded-2xl bg-[var(--color-bg-subtle)]" />
          <div className="h-24 rounded-2xl bg-[var(--color-bg-subtle)]" />
        </div>
      </div>
    </main>
  );
}
