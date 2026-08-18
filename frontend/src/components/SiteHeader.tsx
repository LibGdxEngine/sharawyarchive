import Link from "next/link";

interface SiteHeaderProps {
  /** Prefills the header search box, e.g. on /search. */
  defaultQuery?: string;
}

/**
 * The small header carried by every route except the landing page, where the
 * search field is the hero instead. Exactly one `#site-search` input exists per
 * page — the "/" shortcut focuses it.
 */
export default function SiteHeader({ defaultQuery = "" }: SiteHeaderProps) {
  return (
    <header className="border-b border-[var(--color-border-subtle)]">
      <div className="reading-column flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
        <Link href="/" className="shrink-0 text-base font-semibold">
          أرشيف الشعراوي
        </Link>

        <form action="/search" method="GET" className="min-w-0 flex-1">
          <label htmlFor="site-search" className="sr-only">
            ابحث في الأرشيف
          </label>
          <input
            id="site-search"
            name="q"
            type="search"
            defaultValue={defaultQuery}
            placeholder="ابحث في الأرشيف…"
            autoComplete="off"
            className="w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm placeholder:text-[var(--color-ink-faint)]"
          />
        </form>

        <nav className="flex shrink-0 items-center gap-4 text-sm text-[var(--color-ink-muted)]">
          <Link href="/surahs">الفهرس</Link>
          <Link href="/topics">الموضوعات</Link>
        </nav>
      </div>
    </header>
  );
}
