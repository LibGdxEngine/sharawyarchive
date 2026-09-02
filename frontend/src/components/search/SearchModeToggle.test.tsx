import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SearchModeToggle from "./SearchModeToggle";
import { useSearchMode } from "./useSearchMode";
import { SEARCH_MODE_KEY } from "@/lib/search-mode";

function Harness() {
  const [mode, setMode] = useSearchMode();
  return (
    <>
      <SearchModeToggle mode={mode} onChange={setMode} />
      <output>{mode}</output>
    </>
  );
}

describe("SearchModeToggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("is a controlled pair of pressed buttons", () => {
    const onChange = vi.fn();
    render(<SearchModeToggle mode="smart" onChange={onChange} />);
    const exact = screen.getByRole("button", { name: "بحث دقيق" });
    const smart = screen.getByRole("button", { name: "بحث ذكي" });
    expect(smart.getAttribute("aria-pressed")).toBe("true");
    expect(exact.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(exact);
    expect(onChange).toHaveBeenCalledWith("exact");
  });

  it("remembers the choice through useSearchMode", () => {
    render(<Harness />);
    expect(screen.getByRole("status").textContent).toBe("exact");
    fireEvent.click(screen.getByRole("button", { name: "بحث ذكي" }));
    expect(screen.getByRole("status").textContent).toBe("smart");
    expect(window.localStorage.getItem(SEARCH_MODE_KEY)).toBe("smart");
  });
});
