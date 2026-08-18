/**
 * offline.test.ts
 *
 * Unit tests for the offline library: index bookkeeping, and the save/read
 * round trip that /listen and /saved depend on with no network.
 * Uses happy-dom environment (configured in vitest.config.ts).
 * Stubs the caches API for Cache Storage operations.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  listOfflineSegments,
  isSegmentOffline,
  removeSegmentOffline,
  getOfflineUsageBytes,
  getOfflineAudioUrl,
  getOfflineSegment,
  getOfflineTranscript,
  saveSegmentOffline,
} from "./offline";
import type { OfflineIndexEntry } from "./offline";
import type { Segment, Transcript } from "@/types/models";

// ---------------------------------------------------------------------------
// Helpers — index manipulation via localStorage (mirrors offline.ts internals)
// ---------------------------------------------------------------------------

const INDEX_KEY = "offline:index";

function setIndex(entries: OfflineIndexEntry[]): void {
  localStorage.setItem(INDEX_KEY, JSON.stringify(entries));
}

function getIndex(): OfflineIndexEntry[] {
  const raw = localStorage.getItem(INDEX_KEY);
  return raw ? (JSON.parse(raw) as OfflineIndexEntry[]) : [];
}

function makeEntry(overrides: Partial<OfflineIndexEntry> = {}): OfflineIndexEntry {
  return {
    segmentId: 1,
    title: "الفاتحة",
    bytes: 512_000,
    savedAt: Date.now(),
    ...overrides,
  };
}

function makeSegment(overrides: Partial<Segment> = {}): Segment {
  return {
    id: 1,
    kind: "khawatir",
    title: "الفاتحة",
    surah: 1,
    ayah_start: 1,
    ayah_end: 7,
    duration_ms: 2_400_000,
    ordinal: 3,
    audio_url: "https://cdn.example.com/seg1.opus?signed",
    waveform_url: "https://cdn.example.com/seg1.json?signed",
    source: { title: "تلفزيون", kind: "tv" },
    transcript_version: 2,
    is_human_reviewed: false,
    ...overrides,
  };
}

function makeTranscript(overrides: Partial<Transcript> = {}): Transcript {
  return {
    version: 2,
    engine: "whisper-large-v3",
    is_human_reviewed: false,
    words: [
      { i: 0, t: "بسم", s: 120, e: 480, c: 0.97 },
      // A human-corrected word carries no model confidence.
      { i: 1, t: "الله", s: 480, e: 900, c: null },
    ],
    ...overrides,
  };
}

/**
 * Stands in for the three network fetches a save makes: audio, waveform and
 * transcript, told apart by URL the way the real endpoints are.
 */
function stubFetch(transcript: Transcript) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/transcript/")) {
      return new Response(JSON.stringify(transcript), {
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes(".json")) {
      return new Response(JSON.stringify({ peaks: [0, 1], duration_ms: 1000 }), {
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(new Blob([new Uint8Array([1, 2, 3, 4])]), {
      headers: { "Content-Type": "audio/ogg" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// ---------------------------------------------------------------------------
// Mock Cache Storage
// ---------------------------------------------------------------------------

class FakeCache {
  private _store = new Map<string, Response>();

  async put(key: string, response: Response): Promise<void> {
    this._store.set(key, response);
  }

  async match(key: string): Promise<Response | undefined> {
    return this._store.get(key);
  }

  async delete(key: string): Promise<boolean> {
    return this._store.delete(key);
  }
}

class FakeCacheStorage {
  private _caches = new Map<string, FakeCache>();

  async open(name: string): Promise<FakeCache> {
    if (!this._caches.has(name)) this._caches.set(name, new FakeCache());
    return this._caches.get(name)!;
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async match(_: string): Promise<Response | undefined> {
    return undefined;
  }

  async delete(name: string): Promise<boolean> {
    return this._caches.delete(name);
  }

  async keys(): Promise<string[]> {
    return Array.from(this._caches.keys());
  }

  async has(name: string): Promise<boolean> {
    return this._caches.has(name);
  }
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  localStorage.clear();
  // Stub global caches
  Object.defineProperty(globalThis, "caches", {
    value: new FakeCacheStorage(),
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("listOfflineSegments", () => {
  it("returns an empty array when no entries are saved", () => {
    expect(listOfflineSegments()).toEqual([]);
  });

  it("returns saved entries from localStorage", () => {
    const entries = [makeEntry({ segmentId: 1 }), makeEntry({ segmentId: 2 })];
    setIndex(entries);
    const result = listOfflineSegments();
    expect(result).toHaveLength(2);
    expect(result.map((e) => e.segmentId)).toEqual([1, 2]);
  });

  it("returns a defensive copy (mutations do not affect the index)", () => {
    const entry = makeEntry({ segmentId: 42 });
    setIndex([entry]);
    const list = listOfflineSegments();
    list.push(makeEntry({ segmentId: 99 }));
    // Re-reading should still show only the original entry
    expect(listOfflineSegments()).toHaveLength(1);
  });
});

describe("isSegmentOffline", () => {
  it("returns false when the segment is not in the index", () => {
    expect(isSegmentOffline(7)).toBe(false);
  });

  it("returns true when the segment is present in the index", () => {
    setIndex([makeEntry({ segmentId: 7 })]);
    expect(isSegmentOffline(7)).toBe(true);
  });

  it("returns false for a different segment even when others are saved", () => {
    setIndex([makeEntry({ segmentId: 7 })]);
    expect(isSegmentOffline(8)).toBe(false);
  });
});

describe("removeSegmentOffline", () => {
  it("removes the entry from the index", async () => {
    setIndex([makeEntry({ segmentId: 5 }), makeEntry({ segmentId: 6 })]);
    await removeSegmentOffline(5);
    const remaining = getIndex();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].segmentId).toBe(6);
  });

  it("is idempotent — removing a non-existent entry leaves the index unchanged", async () => {
    setIndex([makeEntry({ segmentId: 5 })]);
    await removeSegmentOffline(99);
    expect(getIndex()).toHaveLength(1);
  });

  it("results in isSegmentOffline returning false after removal", async () => {
    setIndex([makeEntry({ segmentId: 10 })]);
    expect(isSegmentOffline(10)).toBe(true);
    await removeSegmentOffline(10);
    expect(isSegmentOffline(10)).toBe(false);
  });
});

describe("getOfflineUsageBytes", () => {
  it("returns 0 when the index is empty", async () => {
    expect(await getOfflineUsageBytes()).toBe(0);
  });

  it("sums bytes from all index entries", async () => {
    setIndex([
      makeEntry({ segmentId: 1, bytes: 100_000 }),
      makeEntry({ segmentId: 2, bytes: 200_000 }),
    ]);
    expect(await getOfflineUsageBytes()).toBe(300_000);
  });

  it("returns tracked bytes (fast path) without calling navigator.storage", async () => {
    // When the index has tracked bytes, getOfflineUsageBytes returns them
    // directly without consulting navigator.storage (fast path).
    setIndex([makeEntry({ segmentId: 1, bytes: 512_000 })]);
    // Stub navigator.storage.estimate to return a different value
    const originalStorage = Object.getOwnPropertyDescriptor(
      navigator,
      "storage"
    );
    Object.defineProperty(navigator, "storage", {
      value: {
        estimate: async () => ({ usage: 999_999, quota: 10_000_000 }),
        persisted: async () => false,
        persist: async () => true,
        getDirectory: () => Promise.reject(new Error("not available")),
      } as StorageManager,
      configurable: true,
      writable: true,
    });
    const result = await getOfflineUsageBytes();
    // Should return tracked bytes (512_000), not storage estimate (999_999)
    expect(result).toBe(512_000);
    // Restore original descriptor
    if (originalStorage) {
      Object.defineProperty(navigator, "storage", originalStorage);
    } else {
      // If it didn't exist before, remove our stub
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (navigator as any).storage;
    }
  });
});

// ---------------------------------------------------------------------------
// Readers — what /listen and /saved fall back to with no network
// ---------------------------------------------------------------------------

describe("offline readers", () => {
  it("getOfflineSegment returns null when the segment was never saved", async () => {
    expect(await getOfflineSegment(1)).toBeNull();
  });

  it("getOfflineTranscript returns null when the segment was never saved", async () => {
    expect(await getOfflineTranscript(1)).toBeNull();
  });

  it("returns null rather than throwing on a corrupted cached body", async () => {
    const cache = await caches.open("offline-segments");
    await cache.put(
      "/offline/segment/1/transcript",
      new Response("not-valid-json{{{")
    );
    expect(await getOfflineTranscript(1)).toBeNull();
  });
});

describe("saveSegmentOffline round trip", () => {
  it("saves a transcript that getOfflineTranscript reads back", async () => {
    const transcript = makeTranscript();
    stubFetch(transcript);

    await saveSegmentOffline(makeSegment({ id: 17 }));

    expect(await getOfflineTranscript(17)).toEqual(transcript);
  });

  it("saves the segment metadata playback needs offline", async () => {
    stubFetch(makeTranscript());
    const segment = makeSegment({ id: 17, duration_ms: 2_400_000 });

    await saveSegmentOffline(segment);

    // The duration is the reason this is stored: /saved has nothing else to
    // build a seekable track from once the network is gone.
    expect(await getOfflineSegment(17)).toEqual(segment);
  });

  it("requests the transcript version the segment declares", async () => {
    const fetchMock = stubFetch(makeTranscript());

    await saveSegmentOffline(makeSegment({ id: 17, transcript_version: 2 }));

    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(urls.some((url) => url.endsWith("/segments/17/transcript/?v=2"))).toBe(
      true
    );
  });

  it("saves audio that getOfflineAudioUrl can hand to the player", async () => {
    stubFetch(makeTranscript());

    await saveSegmentOffline(makeSegment({ id: 17 }));

    const url = await getOfflineAudioUrl(17);
    expect(url).not.toBeNull();
    if (url !== null) URL.revokeObjectURL(url);
  });

  it("indexes the segment so isSegmentOffline reports it", async () => {
    stubFetch(makeTranscript());

    await saveSegmentOffline(makeSegment({ id: 17, title: "الفاتحة" }));

    expect(isSegmentOffline(17)).toBe(true);
    const [entry] = listOfflineSegments();
    expect(entry.title).toBe("الفاتحة");
    expect(entry.bytes).toBeGreaterThan(0);
  });

  it("forgets everything again on removeSegmentOffline", async () => {
    stubFetch(makeTranscript());
    await saveSegmentOffline(makeSegment({ id: 17 }));

    await removeSegmentOffline(17);

    expect(await getOfflineSegment(17)).toBeNull();
    expect(await getOfflineTranscript(17)).toBeNull();
    expect(isSegmentOffline(17)).toBe(false);
  });
});

describe("index survives malformed localStorage data", () => {
  it("returns an empty array when localStorage contains invalid JSON", () => {
    localStorage.setItem(INDEX_KEY, "not-valid-json{{{");
    expect(listOfflineSegments()).toEqual([]);
  });
});
