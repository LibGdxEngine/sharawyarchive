/*
 * Loading skeleton for /listen/[segmentId].
 *
 * Shared by the route's `loading.tsx` — which paints the moment the link is
 * clicked, before the server has answered — and by `ListenClient`'s own
 * loading state, so the two are never out of step. The blocks mirror the
 * loaded layout (meta line, title, action row, transcript lines) so content
 * arriving does not shift the page.
 */
export default function ListenSkeleton() {
  return (
    <div
      role="status"
      aria-label="جارٍ تحميل المقطع"
      className="reading-column page-shell pt-8"
    >
      <span className="sr-only">جارٍ تحميل المقطع…</span>
      <div aria-hidden className="animate-pulse">
        <div className="h-3 w-40 rounded bg-[var(--color-bg-subtle)]" />
        <div className="mt-2 h-7 w-2/3 rounded bg-[var(--color-bg-subtle)]" />
        <div className="mt-4 flex gap-3">
          <div className="h-6 w-20 rounded bg-[var(--color-bg-subtle)]" />
          <div className="h-6 w-24 rounded bg-[var(--color-bg-subtle)]" />
        </div>
        <div className="mt-6 space-y-3 border-y border-[var(--color-border-subtle)] py-6">
          <div className="h-3 w-full rounded bg-[var(--color-bg-subtle)]" />
          <div className="h-3 w-11/12 rounded bg-[var(--color-bg-subtle)]" />
          <div className="h-3 w-4/5 rounded bg-[var(--color-bg-subtle)]" />
          <div className="h-3 w-full rounded bg-[var(--color-bg-subtle)]" />
          <div className="h-3 w-2/3 rounded bg-[var(--color-bg-subtle)]" />
        </div>
      </div>
    </div>
  );
}
