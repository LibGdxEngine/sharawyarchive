const STORAGE_KEY = "recent:segments";
const MAX_ENTRIES = 5;

export interface RecentSegment {
  segmentId: number;
  title: string;
  kind: "recitation" | "khawatir";
  savedAt: number;
}

// Snapshot cache for useSyncExternalStore: getSnapshot must keep returning
// the SAME array reference while the stored value is unchanged, or React
// re-renders forever. Re-parse only when the raw JSON actually changes.
let cachedRaw: string | null | undefined;
let cachedEntries: RecentSegment[] = [];

function parse(raw: string | null): RecentSegment[] {
  if (!raw) return [];
  try {
    return JSON.parse(raw) as RecentSegment[];
  } catch {
    return [];
  }
}

/** Stable-reference snapshot — safe to hand to useSyncExternalStore. */
export function recentSegmentsSnapshot(): RecentSegment[] {
  if (typeof window === "undefined") return [];
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedEntries = parse(raw);
  }
  return cachedEntries;
}

/** Cross-tab invalidation for useSyncExternalStore. */
export function subscribeRecentSegments(callback: () => void): () => void {
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
}

function readAll(): RecentSegment[] {
  return recentSegmentsSnapshot();
}

function writeAll(entries: RecentSegment[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
}

export function addRecentSegment(
  segmentId: number,
  title: string,
  kind: "recitation" | "khawatir",
): void {
  const entries = readAll().filter((e) => e.segmentId !== segmentId);
  entries.unshift({ segmentId, title, kind, savedAt: Date.now() });
  writeAll(entries.slice(0, MAX_ENTRIES));
}

export function getRecentSegments(): RecentSegment[] {
  return readAll();
}
