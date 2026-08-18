/**
 * Type declarations for the service worker environment.
 *
 * serwist uses InjectManifest which replaces the `self.__SW_MANIFEST`
 * injection point at build time with the actual precache manifest array.
 */

import type { PrecacheEntry } from "serwist";

declare global {
  interface ServiceWorkerGlobalScope {
    __SW_MANIFEST: (PrecacheEntry | string)[];
  }
}

export {};
