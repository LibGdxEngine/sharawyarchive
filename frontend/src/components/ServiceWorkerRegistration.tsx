"use client";

/**
 * ServiceWorkerRegistration — Registers the service worker in production only.
 *
 * Guarded on process.env.NODE_ENV === "production" so the SW is never
 * registered during `next dev`. This component is mounted in the root layout
 * so registration happens on first page visit.
 */

import { useEffect } from "react";

export default function ServiceWorkerRegistration() {
  useEffect(() => {
    if (
      process.env.NODE_ENV !== "production" ||
      !("serviceWorker" in navigator)
    ) {
      return;
    }

    // @serwist/next injects window.serwist when register: true is set in config.
    // Since we handle registration ourselves (register: false in next.config.ts),
    // we fall back to the standard SW registration API.
    const registerSW = async () => {
      try {
        const registration = await navigator.serviceWorker.register("/sw.js", {
          scope: "/",
        });
        registration.addEventListener("updatefound", () => {
          // Silently accept updates — new SW activates on next page load.
        });
      } catch {
        // SW registration failure is non-fatal; app continues normally.
      }
    };

    void registerSW();
  }, []);

  return null;
}
