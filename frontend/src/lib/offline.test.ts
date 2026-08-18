/**
 * offline.test.ts
 *
 * Unit tests for the offline library's index bookkeeping functions.
 * Uses happy-dom environment (configured in vitest.config.ts).
 * Stubs the caches API for Cache Storage operations.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  listOfflineSegments,
  isSegmentOffline,
  removeSegmentOffline,
  getOfflineUsageBytes,
} from "./offline";
import type { OfflineIndexEntry } from "./offline";

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

describe("index survives malformed localStorage data", () => {
  it("returns an empty array when localStorage contains invalid JSON", () => {
    localStorage.setItem(INDEX_KEY, "not-valid-json{{{");
    expect(listOfflineSegments()).toEqual([]);
  });
});
