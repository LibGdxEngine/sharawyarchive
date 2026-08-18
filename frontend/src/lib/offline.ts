/**
 * offline.ts — Save-for-offline per segment
 *
 * Stores audio, waveform, and transcript for a segment in Cache Storage
 * ("offline-segments" cache) under stable synthetic keys, and maintains an
 * index in localStorage ("offline:index") with lightweight metadata.
 *
 * All public timestamps are integer milliseconds (consistent with the rest
 * of the codebase).
 */

const CACHE_NAME = "offline-segments";
const INDEX_KEY = "offline:index";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OfflineIndexEntry {
  segmentId: number;
  title: string;
  /** Combined byte size of audio + waveform + transcript stored. */
  bytes: number;
  /** Unix timestamp (ms) when the segment was saved. */
  savedAt: number;
}

// ---------------------------------------------------------------------------
// Synthetic cache keys
// ---------------------------------------------------------------------------

function audioKey(segmentId: number): string {
  return `/offline/segment/${segmentId}/audio`;
}
function waveformKey(segmentId: number): string {
  return `/offline/segment/${segmentId}/waveform`;
}
function transcriptKey(segmentId: number): string {
  return `/offline/segment/${segmentId}/transcript`;
}

// ---------------------------------------------------------------------------
// Index helpers (localStorage)
// ---------------------------------------------------------------------------

function readIndex(): OfflineIndexEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(INDEX_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as OfflineIndexEntry[];
  } catch {
    return [];
  }
}

function writeIndex(entries: OfflineIndexEntry[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(INDEX_KEY, JSON.stringify(entries));
}

function indexEntry(segmentId: number): OfflineIndexEntry | undefined {
  return readIndex().find((e) => e.segmentId === segmentId);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** List all saved segments (from the localStorage index). */
export function listOfflineSegments(): OfflineIndexEntry[] {
  return readIndex();
}

/** Returns true if the segment has been saved for offline use. */
export function isSegmentOffline(segmentId: number): boolean {
  return indexEntry(segmentId) !== undefined;
}

/**
 * Returns a Blob URL for the offline audio of a segment, or null if not saved.
 * The caller is responsible for revoking the object URL when done.
 */
export async function getOfflineAudioUrl(
  segmentId: number
): Promise<string | null> {
  if (typeof window === "undefined" || !("caches" in window)) return null;
  try {
    const cache = await caches.open(CACHE_NAME);
    const response = await cache.match(audioKey(segmentId));
    if (!response) return null;
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  } catch {
    return null;
  }
}

/**
 * Returns the total bytes tracked in the index (fast path).
 * Falls back to navigator.storage.estimate() if available.
 */
export async function getOfflineUsageBytes(): Promise<number> {
  const tracked = readIndex().reduce((acc, e) => acc + e.bytes, 0);
  if (tracked > 0) return tracked;
  if (
    typeof navigator !== "undefined" &&
    "storage" in navigator &&
    "estimate" in navigator.storage
  ) {
    try {
      const est = await navigator.storage.estimate();
      return est.usage ?? 0;
    } catch {
      return 0;
    }
  }
  return 0;
}

/**
 * Save a segment for offline playback.
 * Fetches audio_url, waveform_url, and transcript, caches them all, then
 * records a summary entry in the localStorage index.
 *
 * @param segmentId  Numeric segment ID.
 * @param meta       Pre-fetched segment metadata (avoids re-fetching from the
 *                   network; the /listen page already has this).
 * @param onProgress Called with a fraction [0, 1] as each resource is saved.
 */
export async function saveSegmentOffline(
  segmentId: number,
  meta: {
    title: string;
    audio_url: string;
    waveform_url: string;
  },
  onProgress?: (fraction: number) => void
): Promise<void> {
  if (!("caches" in window)) {
    throw new Error("Cache Storage not available");
  }

  const cache = await caches.open(CACHE_NAME);
  const apiBase =
    (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api").replace(
      /\/$/,
      ""
    );

  let totalBytes = 0;
  onProgress?.(0);

  // ---- 1. Audio (largest resource, count first)
  const audioResponse = await fetch(meta.audio_url);
  if (!audioResponse.ok) throw new Error(`Failed to fetch audio: ${audioResponse.status}`);
  const audioBlob = await audioResponse.blob();
  totalBytes += audioBlob.size;
  await cache.put(
    audioKey(segmentId),
    new Response(audioBlob, {
      headers: { "Content-Type": audioBlob.type || "audio/ogg" },
    })
  );
  onProgress?.(0.6);

  // ---- 2. Waveform JSON
  const waveformResponse = await fetch(meta.waveform_url);
  if (!waveformResponse.ok)
    throw new Error(`Failed to fetch waveform: ${waveformResponse.status}`);
  const waveformBlob = await waveformResponse.blob();
  totalBytes += waveformBlob.size;
  await cache.put(
    waveformKey(segmentId),
    new Response(waveformBlob, {
      headers: { "Content-Type": "application/json" },
    })
  );
  onProgress?.(0.8);

  // ---- 3. Transcript JSON
  const transcriptUrl = `${apiBase}/segments/${segmentId}/transcript/`;
  const transcriptResponse = await fetch(transcriptUrl);
  if (!transcriptResponse.ok)
    throw new Error(`Failed to fetch transcript: ${transcriptResponse.status}`);
  const transcriptBlob = await transcriptResponse.blob();
  totalBytes += transcriptBlob.size;
  await cache.put(
    transcriptKey(segmentId),
    new Response(transcriptBlob, {
      headers: { "Content-Type": "application/json" },
    })
  );
  onProgress?.(0.95);

  // ---- 4. Update index
  const existing = readIndex().filter((e) => e.segmentId !== segmentId);
  writeIndex([
    ...existing,
    {
      segmentId,
      title: meta.title,
      bytes: totalBytes,
      savedAt: Date.now(),
    },
  ]);
  onProgress?.(1);
}

/**
 * Remove an offline segment from Cache Storage and the index.
 */
export async function removeSegmentOffline(segmentId: number): Promise<void> {
  if (!("caches" in window)) return;
  const cache = await caches.open(CACHE_NAME);
  await Promise.all([
    cache.delete(audioKey(segmentId)),
    cache.delete(waveformKey(segmentId)),
    cache.delete(transcriptKey(segmentId)),
  ]);
  writeIndex(readIndex().filter((e) => e.segmentId !== segmentId));
}
