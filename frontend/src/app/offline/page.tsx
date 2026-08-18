/**
 * /offline — Static fallback shown by the service worker when the user
 * navigates to a page that is not cached and the network is unavailable.
 */

import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "غير متصل — أرشيف الشعراوي",
};

// This page is static — no API calls, no dynamic data.
export const dynamic = "force-static";

export default function OfflinePage() {
  return (
    <main className="reading-column page-shell flex min-h-[60vh] flex-col items-center justify-center gap-6 text-center">
      <div
        className="flex h-16 w-16 items-center justify-center rounded-full"
        style={{ backgroundColor: "var(--color-bg-subtle)" }}
      >
        {/* Offline icon — simple SVG, no external resources */}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="32"
          height="32"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          style={{ color: "var(--color-ink-muted)" }}
        >
          <line x1="1" y1="1" x2="23" y2="23" />
          <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
          <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
          <path d="M10.71 5.05A16 16 0 0 1 22.56 9" />
          <path d="M1.42 9a16 16 0 0 1 4.7-2.88" />
          <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
          <line x1="12" y1="20" x2="12.01" y2="20" />
        </svg>
      </div>

      <div>
        <h1
          className="text-lg font-semibold"
          style={{ color: "var(--color-ink)" }}
        >
          أنت غير متصل — المحفوظات متاحة
        </h1>
        <p
          className="mt-2 text-sm leading-relaxed"
          style={{ color: "var(--color-ink-muted)" }}
        >
          تعذّر الوصول إلى هذه الصفحة. يمكنك الاستماع إلى المقاطع التي حفظتها
          مسبقًا.
        </p>
      </div>

      <Link
        href="/saved"
        className="rounded px-4 py-2 text-sm font-medium transition-colors"
        style={{
          backgroundColor: "var(--color-accent)",
          color: "#ffffff",
        }}
      >
        المقاطع المحفوظة
      </Link>
    </main>
  );
}
