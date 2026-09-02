import { describe, expect, it } from "vitest";
import { ayahPlaceholders, parseAnswer } from "./smart-answer";

const options = { citationCount: 2, ayahKeys: new Set(["2:255"]) };

describe("parseAnswer", () => {
  it("turns markers into typed nodes and keeps the rest literal", () => {
    const [paragraph] = parseAnswer("قال الشيخ صراحةً [1] كذا [[ayah:2:255]] وكذا [2].", options);
    expect(paragraph.nodes).toEqual([
      { type: "text", text: "قال الشيخ صراحةً " },
      { type: "cite", n: 1 },
      { type: "text", text: " كذا " },
      { type: "ayah", surah: 2, ayah: 255 },
      { type: "text", text: " وكذا " },
      { type: "cite", n: 2 },
      { type: "text", text: "." },
    ]);
  });

  it("drops markers that point at nothing", () => {
    const [paragraph] = parseAnswer("نص [3] آخر [[ayah:2:9999]] [0] تمام", options);
    expect(paragraph.nodes).toEqual([{ type: "text", text: "نص آخر تمام" }]);
  });

  it("splits paragraphs on newlines and skips blank ones", () => {
    const paragraphs = parseAnswer("أول [1].\n\n  \nثانٍ [2].\r\n", options);
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[1].nodes[0]).toEqual({ type: "text", text: "ثانٍ " });
  });

  it("never interprets markup", () => {
    const [paragraph] = parseAnswer("<b>x</b> **y** [link](http://e)", options);
    expect(paragraph.nodes).toEqual([{ type: "text", text: "<b>x</b> **y** [link](http://e)" }]);
  });

  it("handles an empty answer", () => {
    expect(parseAnswer("", options)).toEqual([]);
    expect(parseAnswer("[1][1]", { ...options, citationCount: 0 })).toEqual([]);
  });
});

describe("ayahPlaceholders", () => {
  it("lists each placeholder once, in order", () => {
    expect(ayahPlaceholders("[[ayah:2:255]] و [[ayah:24:35]] ثم [[ayah:2:255]]")).toEqual([
      { surah: 2, ayah: 255 },
      { surah: 24, ayah: 35 },
    ]);
    expect(ayahPlaceholders("لا شيء")).toEqual([]);
  });
});
