import { describe, expect, it } from "vitest";
import { normalizeForIndex, normalizeLight, tokenizeNormalized } from "./arabic";
import pairs from "./__fixtures__/normalization_pairs.json";

interface NormalizationPair {
  note: string;
  input: string;
  light: string;
  index: string;
}

/**
 * Data-driven parity suite — the same fixture the backend runs against
 * `corpus.arabic` (`backend/corpus/tests/test_arabic.py`). The two copies of
 * `normalization_pairs.json` are asserted byte-identical by
 * `backend/corpus/tests/test_frontend_fixture_sync.py`, so passing here means
 * this port and the Python module agree on every documented case.
 */
describe("normalizeLight", () => {
  it.each(pairs as NormalizationPair[])("$note", ({ input, light }) => {
    expect(normalizeLight(input)).toBe(light);
  });
});

describe("normalizeForIndex", () => {
  it.each(pairs as NormalizationPair[])("$note", ({ input, index }) => {
    expect(normalizeForIndex(input)).toBe(index);
  });

  it("is idempotent on every fixture output", () => {
    for (const { index } of pairs as NormalizationPair[]) {
      expect(normalizeForIndex(index)).toBe(index);
    }
  });
});

describe("tokenizeNormalized", () => {
  it("returns no tokens for empty or mark-only input", () => {
    expect(tokenizeNormalized("")).toEqual([]);
    expect(tokenizeNormalized("ًٌٍَُِّْ")).toEqual([]);
  });

  it("splits on the collapsed single spaces", () => {
    expect(tokenizeNormalized("  لِمَن   شَاءَ ")).toEqual(["لمن", "شاء"]);
  });
});
