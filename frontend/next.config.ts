import type { NextConfig } from "next";
import withSerwistInit from "@serwist/next";
import { withSentryConfig } from "@sentry/nextjs";

/**
 * Cache-busting token for the precached /offline document. Serwist re-fetches a
 * precached entry only when its revision changes, and the page's own content
 * hash is not visible here — so bump this string whenever src/app/offline
 * changes.
 */
const OFFLINE_FALLBACK_REVISION = "1";

const withSerwist = withSerwistInit({
  swSrc: "src/sw.ts",
  swDest: "public/sw.js",
  // Disable in dev — registered only in production builds
  disable: process.env.NODE_ENV === "development",
  // Automatically register the SW via @serwist/next injected script
  register: false, // we register manually to guard NODE_ENV
  // The SW's navigation fallback (see `fallbacks` in src/sw.ts) can only be
  // served from the precache, and Next's build manifest carries static assets
  // rather than rendered documents — so the fallback page is added by hand.
  additionalPrecacheEntries: [
    { url: "/offline", revision: OFFLINE_FALLBACK_REVISION },
  ],
});

const nextConfig: NextConfig = {
  output: "standalone",
};

const withServiceWorker = withSerwist(nextConfig);

/*
 * Sentry wraps the Serwist-wrapped config, not the other way round, so the
 * service worker is still bundled exactly as before.
 *
 * The wrapper is applied only when SENTRY_DSN is present at build time: the
 * build plugin otherwise adds nothing but noise, and source-map upload needs
 * credentials the default build has no reason to carry.
 */
export default process.env.SENTRY_DSN
  ? withSentryConfig(withServiceWorker, {
      silent: true,
      telemetry: false,
      // Uploading source maps needs an auth token + org/project; releases are
      // built without one, so keep the plugin to instrumentation duties only.
      sourcemaps: { disable: true },
    })
  : withServiceWorker;
