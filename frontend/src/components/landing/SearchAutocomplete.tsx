"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import SearchModeToggle from "@/components/search/SearchModeToggle";
import { searchHref, SEARCH_PLACEHOLDER, type SearchMode } from "@/lib/search-mode";

export type SearchKind = "all" | "recitation" | "khawatir";

const KIND_OPTIONS: { value: SearchKind; label: string }[] = [
  { value: "all", label: "الكل" },
  { value: "recitation", label: "تلاوة" },
  { value: "khawatir", label: "خواطر" },
];

interface SearchAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  kind: SearchKind;
  onKindChange: (kind: SearchKind) => void;
  mode: SearchMode;
  onModeChange: (mode: SearchMode) => void;
}

/**
 * The landing search hero. Controlled by its parent (SearchHero) so the
 * recommendation chips can fill the input, but owns its own suggestion
 * fetching, keyboard cycling and the "/" fast-focus (`id="site-search"`).
 */
export default function SearchAutocomplete({
  value,
  onChange,
  kind,
  onKindChange,
  mode,
  onModeChange,
}: SearchAutocompleteProps) {
  const router = useRouter();
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [isOpen, setIsOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const fetchSuggestions = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setSuggestions([]);
      setIsOpen(false);
      return;
    }

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const BASE_URL = (
      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"
    ).replace(/\/$/, "");

    try {
      const kindParam = kind === "all" ? "" : `&kind=${kind}`;
      const res = await fetch(
        `${BASE_URL}/search/suggest/?q=${encodeURIComponent(q)}${kindParam}`,
        { signal: controller.signal },
      );
      if (!res.ok) return;
      const data: string[] = await res.json();
      setSuggestions(data);
      setIsOpen(data.length > 0);
      setActiveIndex(-1);
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") return;
    }
  }, [kind]);

  useEffect(() => {
    const timer = setTimeout(() => fetchSuggestions(value), 200);
    return () => clearTimeout(timer);
  }, [value, fetchSuggestions]);

  const selectSuggestion = (text: string) => {
    setIsOpen(false);
    onChange(text);
    router.push(searchHref(text, kind, mode));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || suggestions.length === 0) {
      if (e.key === "Escape") {
        setIsOpen(false);
        setActiveIndex(-1);
      }
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((prev) => {
        const next = prev + 1;
        return next >= suggestions.length ? 0 : next;
      });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((prev) => {
        const next = prev - 1;
        return next < 0 ? suggestions.length - 1 : next;
      });
    } else if (e.key === "Escape") {
      setIsOpen(false);
      setActiveIndex(-1);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    if (isOpen && activeIndex >= 0 && activeIndex < suggestions.length) {
      e.preventDefault();
      selectSuggestion(suggestions[activeIndex]);
    }
  };

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const form = document.getElementById("landing-search-form");
      if (form && !form.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div className="relative w-full">
      <form
        id="landing-search-form"
        action="/search"
        method="GET"
        className="landing-search flex w-full flex-col gap-2 rounded-2xl p-3"
        onSubmit={handleSubmit}
      >
        <div className="flex w-full flex-wrap gap-2">
          <span
            aria-hidden
            className="self-center ps-2 text-[var(--landing-gold)]"
          >
            <svg
              viewBox="0 0 24 24"
              width={20}
              height={20}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              className="block"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="M16.5 16.5 21 21" />
            </svg>
          </span>
          <label htmlFor="site-search" className="sr-only">
            ابحث في الأرشيف
          </label>
          <input
            id="site-search"
            name="q"
            type="search"
            placeholder={SEARCH_PLACEHOLDER[mode]}
            autoComplete="off"
            autoFocus
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            className="min-w-0 flex-1 basis-[160px] border-none bg-transparent px-1 py-1.5 text-lg text-[var(--landing-ink)] placeholder:text-[var(--landing-placeholder)]"
          />
          <button
            type="submit"
            className="cursor-pointer whitespace-nowrap rounded-xl bg-[var(--landing-gold)] px-6 py-2.5 text-base font-semibold text-[var(--landing-btn-ink)] transition-colors hover:bg-[var(--landing-gold-hover)] max-[480px]:w-full"
          >
            ابدأ البحث
          </button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 ps-2">
          <span className="flex flex-wrap items-center gap-2">
            <span
              className="landing-kind"
              role="group"
              aria-label="نوع المحتوى"
            >
              {KIND_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={kind === option.value}
                  onClick={() => onKindChange(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </span>
            <SearchModeToggle mode={mode} onChange={onModeChange} className="landing-mode" />
          </span>
          {kind !== "all" && <input type="hidden" name="kind" value={kind} />}
          {mode === "smart" && <input type="hidden" name="mode" value="smart" />}
          <span className="hidden text-xs text-[var(--landing-ink-4)] sm:inline">
            اضغط / للبحث السريع
          </span>
        </div>
      </form>

      {isOpen && suggestions.length > 0 && (
        <ul
          role="listbox"
          aria-label="اقتراحات البحث"
          className="absolute inset-x-0 top-full z-50 mt-2 overflow-hidden rounded-xl border border-[var(--landing-box-border)] bg-[var(--landing-box-bg)] text-start shadow-[var(--landing-shadow)]"
        >
          {suggestions.map((text, i) => (
            <li
              key={i}
              role="option"
              aria-selected={i === activeIndex}
              onMouseDown={(e) => {
                e.preventDefault();
                selectSuggestion(text);
              }}
              onMouseEnter={() => setActiveIndex(i)}
              className={`flex items-center gap-3 border-b border-[var(--landing-chip-border)] px-5 py-3 text-sm text-[var(--landing-ink-3)] last:border-b-0 ${
                i === activeIndex
                  ? "bg-[var(--landing-chip-bg)] text-[var(--landing-chip-ink-hover)]"
                  : ""
              }`}
            >
              <span aria-hidden className="text-[var(--landing-gold)]">
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 12 12"
                  fill="none"
                  className="mt-0.5 shrink-0"
                >
                  <rect
                    x="3"
                    y="3"
                    width="6"
                    height="6"
                    stroke="currentColor"
                    strokeWidth="1"
                  />
                  <rect
                    x="3"
                    y="3"
                    width="6"
                    height="6"
                    stroke="currentColor"
                    strokeWidth="1"
                    transform="rotate(45 6 6)"
                  />
                </svg>
              </span>
              <span className="leading-snug">{text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
