import { describe, expect, it } from "vitest";
import { formatMs, parseMs } from "./format";

describe("parseMs", () => {
  it("round-trips whatever formatMs prints", () => {
    for (const ms of [0, 9_000, 59_000, 60_000, 3_599_000, 3_600_000, 5_060_000]) {
      expect(parseMs(formatMs(ms))).toBe(ms);
    }
  });

  it("reads the shapes a reader actually types", () => {
    expect(parseMs("45")).toBe(45_000);
    expect(parseMs("2:05")).toBe(125_000);
    expect(parseMs("02:05")).toBe(125_000);
    expect(parseMs("1:02:05")).toBe(3_725_000);
    expect(parseMs("  2:05  ")).toBe(125_000);
  });

  it("lets the leading field overflow its base", () => {
    // "90:00" is how you say 1h30m into an 84-minute segment.
    expect(parseMs("90:00")).toBe(5_400_000);
  });

  it("accepts an Arabic keyboard's digits and separators", () => {
    expect(parseMs("٢:٠٥")).toBe(125_000);
    expect(parseMs("2.05")).toBe(125_000);
  });

  it("returns null rather than guessing", () => {
    for (const bad of ["", "   ", "abc", "2:5:", "1:2:3:4", "2:75", "1:70:00", "-5"]) {
      expect(parseMs(bad)).toBeNull();
    }
  });
});
