// Service Worker — Sha'rawy Archive PWA
//
// Compiled by @serwist/next (webpack InjectManifest plugin).
// This file is the SW entry point; serwist injects the precache manifest
// and adds event listeners via Serwist.addEventListeners().
//
// Caching policies:
//  - Precache: app shell (/_next/static/, fonts, public assets)
//  - /api/segments/<id>/transcript -> stale-while-revalidate (cache: "transcripts")
//  - /api/surahs + /api/ayahs     -> cache-first, 30-day expiry  (cache: "quran")
//  - /api/search                  -> network-only (never cached)
//  - navigation requests          -> network-first, fallback to /offline
//  - offline segment assets       -> served from "offline-segments" (managed by offline.ts)

import { defaultCache } from "@serwist/next/worker";
import {
  Serwist,
  StaleWhileRevalidate,
  CacheFirst,
  NetworkOnly,
} from "serwist";
import type { PrecacheEntry } from "serwist";

// ---------------------------------------------------------------------------
// Service worker global scope augmentation
// ---------------------------------------------------------------------------
// This declaration is needed so TypeScript knows about `self.__SW_MANIFEST`,
// which @serwist/next's InjectManifest plugin replaces at build time with the
// actual precache manifest entries.
declare global {
  interface ServiceWorkerGlobalScope {
    __SW_MANIFEST: (PrecacheEntry | string)[];
  }
}

declare const self: ServiceWorkerGlobalScope;

const OFFLINE_FALLBACK = "/offline";
const OFFLINE_SEGMENTS_CACHE = "offline-segments";

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [
    // 1. Transcript endpoints — stale-while-revalidate
    {
      matcher: ({ url }: { url: URL }) =>
        url.pathname.startsWith("/api/") &&
        url.pathname.includes("/transcript"),
      handler: new StaleWhileRevalidate({
        cacheName: "transcripts",
      }),
    },
    // 2. Quran data (surahs + ayahs) — cache-first, 30 days
    {
      matcher: ({ url }: { url: URL }) =>
        url.pathname === "/api/surahs/" ||
        url.pathname.startsWith("/api/surahs/") ||
        url.pathname.startsWith("/api/ayahs/"),
      handler: new CacheFirst({
        cacheName: "quran",
        plugins: [
          {
            cachedResponseWillBeUsed: async ({ cachedResponse }) => {
              if (!cachedResponse) return null;
              // 30-day TTL check via Date header
              const dateStr = cachedResponse.headers.get("date");
              if (dateStr) {
                const cachedAt = new Date(dateStr).getTime();
                const maxAge = 30 * 24 * 60 * 60 * 1000; // 30 days in ms
                if (Date.now() - cachedAt > maxAge) return null;
              }
              return cachedResponse;
            },
          },
        ],
      }),
    },
    // 3. Search — network-only (never cached)
    {
      matcher: ({ url }: { url: URL }) =>
        url.pathname.startsWith("/api/search"),
      handler: new NetworkOnly(),
    },
    // 4. Offline segment assets managed by offline.ts in Cache Storage.
    //    These are served from "offline-segments" (populated by offline.ts).
    {
      matcher: ({ url }: { url: URL }) =>
        url.pathname.startsWith("/offline/segment/"),
      handler: new CacheFirst({
        cacheName: OFFLINE_SEGMENTS_CACHE,
      }),
    },
    // 5. Default Next.js caching from @serwist/next
    ...defaultCache,
  ],
  fallbacks: {
    entries: [
      {
        url: OFFLINE_FALLBACK,
        matcher({ request }: { request: Request }) {
          return request.destination === "document";
        },
      },
    ],
  },
});

serwist.addEventListeners();
