import { Suspense } from "react";
import SiteHeader, { SiteHeaderShell } from "@/components/SiteHeader";

/**
 * Every route except the landing page lives in this group so the header renders
 * exactly once, above `{children}`.
 *
 * The Suspense boundary is mandatory, not decorative: `SiteHeader` calls
 * `useSearchParams()`, which forces client-side rendering up to the nearest
 * boundary — without one, prerendering `/offline` (`dynamic = "force-static"`)
 * fails the build. The fallback is the same hookless shell, so the prerendered
 * HTML matches the hydrated markup; only the active-link state lags one frame.
 */
export default function SiteLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <>
      <Suspense fallback={<SiteHeaderShell activePath={null} defaultQuery="" />}>
        <SiteHeader />
      </Suspense>
      {children}
    </>
  );
}
