/**
 * Browser-side observability hook.
 *
 * `NEXT_PUBLIC_SENTRY_DSN` is inlined at build time, so when it is unset the
 * whole block below is dead code: the bundler drops it and the Sentry SDK is
 * never fetched by the browser. Absence of the variable costs zero bytes.
 */

const DSN = process.env.NEXT_PUBLIC_SENTRY_DSN ?? "";

if (DSN !== "") {
  void import("@sentry/nextjs").then((Sentry) => {
    Sentry.init({
      dsn: DSN,
      tracesSampleRate: 0,
      // Nothing here is worth replaying, and session replay would ship a large
      // extra bundle to readers on slow connections.
      replaysOnErrorSampleRate: 0,
      replaysSessionSampleRate: 0,
    });
  });
}

/** Next's navigation hook — a no-op without a DSN, like everything else here. */
export function onRouterTransitionStart(
  href: string,
  navigationType: string
): void {
  if (DSN === "") return;
  void import("@sentry/nextjs").then((Sentry) => {
    Sentry.captureRouterTransitionStart(href, navigationType);
  });
}
