import { beforeEach, describe, expect, it } from "vitest";
import {
  parseSearchMode,
  readStoredMode,
  SEARCH_MODE_KEY,
  searchHref,
  storeMode,
} from "./search-mode";

describe("parseSearchMode", () => {
  it("is smart only when told so", () => {
    expect(parseSearchMode("smart")).toBe("smart");
    expect(parseSearchMode(["smart", "exact"])).toBe("smart");
    expect(parseSearchMode("exact")).toBe("exact");
    expect(parseSearchMode("SMART")).toBe("exact");
    expect(parseSearchMode(undefined)).toBe("exact");
    expect(parseSearchMode(null)).toBe("exact");
  });
});

describe("searchHref", () => {
  it("only names what departs from the defaults", () => {
    expect(searchHref("الصبر", undefined)).toBe("/search?q=%D8%A7%D9%84%D8%B5%D8%A8%D8%B1");
    expect(searchHref("a b", "all", "exact")).toBe("/search?q=a+b");
    expect(searchHref("a", "khawatir", "exact")).toBe("/search?q=a&kind=khawatir");
    expect(searchHref("a", "recitation", "smart")).toBe("/search?q=a&kind=recitation&mode=smart");
    expect(searchHref("a", undefined, "smart")).toBe("/search?q=a&mode=smart");
  });
});

describe("stored mode", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("defaults to exact and round-trips a stored choice", () => {
    expect(readStoredMode()).toBe("exact");
    storeMode("smart");
    expect(window.localStorage.getItem(SEARCH_MODE_KEY)).toBe("smart");
    expect(readStoredMode()).toBe("smart");
    window.localStorage.setItem(SEARCH_MODE_KEY, "garbage");
    expect(readStoredMode()).toBe("exact");
  });
});
