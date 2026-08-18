/**
 * keyboard-target.test.ts
 *
 * Which targets swallow the transport shortcuts and which do not.
 * Uses happy-dom environment (configured in vitest.config.ts).
 */

import { describe, it, expect } from "vitest";
import { isTypingTarget, TRANSCRIPT_WORD_ATTRIBUTE } from "./keyboard-target";

function element(tag: string, attributes: Record<string, string> = {}) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    el.setAttribute(name, value);
  }
  return el;
}

describe("isTypingTarget", () => {
  it.each(["input", "textarea", "select", "button", "a"])(
    "treats <%s> as a typing target",
    (tag) => {
      expect(isTypingTarget(element(tag))).toBe(true);
    }
  );

  it("treats a contenteditable element as a typing target", () => {
    const el = element("div");
    el.setAttribute("contenteditable", "true");
    expect(isTypingTarget(el)).toBe(true);
  });

  it.each(["div", "p", "span", "body"])("leaves <%s> to the transport", (tag) => {
    expect(isTypingTarget(element(tag))).toBe(false);
  });

  it("returns false for a null target", () => {
    expect(isTypingTarget(null)).toBe(false);
  });

  it("returns false for a non-element event target", () => {
    expect(isTypingTarget(new EventTarget())).toBe(false);
  });

  it("leaves a transcript word button to the transport", () => {
    // Regression: every transcript word is a <button>, so classifying buttons
    // as typing targets meant Space re-clicked the focused word forever
    // instead of pausing playback.
    const word = element("button", { [TRANSCRIPT_WORD_ATTRIBUTE]: "" });
    expect(isTypingTarget(word)).toBe(false);
  });

  it("still leaves ordinary buttons alone", () => {
    expect(isTypingTarget(element("button"))).toBe(true);
  });
});
