"use client";

import { useRouter } from "next/navigation";
import SearchModeToggle from "./SearchModeToggle";
import { searchHref, storeMode, type SearchKindParam, type SearchMode } from "@/lib/search-mode";

interface SearchModeBarProps {
  query: string;
  kind: SearchKindParam;
  mode: SearchMode;
}

/** The toggle on /search: switching modes re-runs the same query the other way. */
export default function SearchModeBar({ query, kind, mode }: SearchModeBarProps) {
  const router = useRouter();
  return (
    <SearchModeToggle
      mode={mode}
      className="mt-3"
      onChange={(next) => {
        if (next === mode) return;
        storeMode(next);
        router.push(searchHref(query, kind, next));
      }}
    />
  );
}
