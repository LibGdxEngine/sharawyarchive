"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";
import { parseSearchMode, SEARCH_PLACEHOLDER, type SearchMode } from "@/lib/search-mode";
import { SITE_NAME } from "@/lib/site";

const NAV_LINKS = [
  { href: "/surahs", label: "الفهرس" },
  { href: "/topics", label: "الموضوعات" },
  { href: "/saved", label: "المحفوظة" },
] as const;

const MOBILE_PANEL_ID = "site-nav-panel";

/** Weight/colour only — the accent is reserved for the active word and focus rings. */
function linkClass(isActive: boolean): string {
  return isActive
    ? "font-medium text-[var(--color-ink)]"
    : "text-[var(--color-ink-muted)]";
}

/** Eight-point star — the archive's ornamental mark, drawn in currentColor. */
function SiteMark() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="currentColor"
      aria-hidden="true"
      className="shrink-0"
    >
      <path d="M12 1.5 15 6h-6zM12 22.5 9 18h6zM1.5 12 6 9v6zM22.5 12 18 15V9zM4.6 4.6l5.3 1.4-4 4zM19.4 19.4l-5.3-1.4 4-4zM19.4 4.6l-1.4 5.3-4-4zM4.6 19.4l1.4-5.3 4 4z" />
    </svg>
  );
}

interface SiteHeaderShellProps {
  /** Current pathname, or `null` while the URL-reading header is still suspended. */
  activePath: string | null;
  /** Prefills the header search box, e.g. on /search. */
  defaultQuery: string;
  /** Keeps a smart-mode search in smart mode when re-searched from the header. */
  defaultMode?: SearchMode;
}

/**
 * The header markup. Deliberately free of URL-reading hooks so it can also serve
 * as the Suspense fallback for {@link SiteHeader} without a markup mismatch —
 * only the mobile disclosure state lives here, and plain `useState` never forces
 * a client-side-rendering bailout the way `useSearchParams` does.
 *
 * Exactly one `#site-search` input exists per page — the "/" shortcut focuses it.
 */
export function SiteHeaderShell({
  activePath,
  defaultQuery,
  defaultMode = "exact",
}: SiteHeaderShellProps) {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-30 border-b border-[var(--color-border-subtle)] bg-[var(--color-surface)]/90 backdrop-blur-[8px]">
      <div className="reading-column flex items-center gap-x-3 py-3 sm:gap-x-4">
        <Link
          href="/"
          className="flex shrink-0 items-center gap-2 text-base font-semibold"
        >
          <SiteMark />
          {SITE_NAME}
        </Link>

        <form action="/search" method="GET" className="min-w-0 flex-1">
          <label htmlFor="site-search" className="sr-only">
            ابحث في الأرشيف
          </label>
          <input
            id="site-search"
            name="q"
            type="search"
            // Remount when the query changes so the prefill tracks the URL —
            // the header now lives in a layout that survives navigation.
            key={`${defaultMode}:${defaultQuery}`}
            defaultValue={defaultQuery}
            placeholder={defaultMode === "smart" ? SEARCH_PLACEHOLDER.smart : "ابحث في الأرشيف…"}
            autoComplete="off"
            className="w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm placeholder:text-[var(--color-ink-faint)]"
          />
          {defaultMode === "smart" ? <input type="hidden" name="mode" value="smart" /> : null}
        </form>

        <nav className="hidden shrink-0 items-center gap-4 text-sm sm:flex">
          {NAV_LINKS.map(({ href, label }) => {
            const isActive = activePath === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={isActive ? "page" : undefined}
                className={linkClass(isActive)}
              >
                {label}
              </Link>
            );
          })}
        </nav>

        <button
          type="button"
          onClick={() => setOpen((previous) => !previous)}
          aria-expanded={open}
          aria-controls={MOBILE_PANEL_ID}
          aria-label="القائمة"
          className="shrink-0 rounded border border-[var(--color-border)] p-1.5 text-[var(--color-ink-muted)] sm:hidden"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            {open ? (
              <>
                <line x1="5" y1="5" x2="19" y2="19" />
                <line x1="19" y1="5" x2="5" y2="19" />
              </>
            ) : (
              <>
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </>
            )}
          </svg>
        </button>
      </div>

      {open ? (
        <nav
          id={MOBILE_PANEL_ID}
          className="reading-column flex flex-col border-t border-[var(--color-border-subtle)] pb-2 text-sm sm:hidden"
        >
          {NAV_LINKS.map(({ href, label }) => {
            const isActive = activePath === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={isActive ? "page" : undefined}
                onClick={() => setOpen(false)}
                className={`py-2 ${linkClass(isActive)}`}
              >
                {label}
              </Link>
            );
          })}
        </nav>
      ) : null}
    </header>
  );
}

/**
 * The header carried by every route in the `(site)` group. It reads the URL
 * itself — layouts never re-render on navigation, so the pathname and `?q=`
 * have to come from the client hooks. That forces client-side rendering up to
 * the nearest Suspense boundary, which `(site)/layout.tsx` supplies.
 */
export default function SiteHeader() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const onSearch = pathname === "/search";
  const defaultQuery = onSearch ? (searchParams.get("q") ?? "") : "";
  const defaultMode = onSearch ? parseSearchMode(searchParams.get("mode")) : "exact";

  return (
    <SiteHeaderShell
      activePath={pathname}
      defaultQuery={defaultQuery}
      defaultMode={defaultMode}
    />
  );
}
