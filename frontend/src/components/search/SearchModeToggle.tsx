import { MODE_LABEL, type SearchMode } from "@/lib/search-mode";

interface SearchModeToggleProps {
  mode: SearchMode;
  onChange: (mode: SearchMode) => void;
  className?: string;
}

const MODES: SearchMode[] = ["exact", "smart"];

/**
 * The «بحث دقيق / بحث ذكي» segmented control. Hook-free and controlled, so
 * the landing box, the results header and the site header can all use it
 * with whatever state they own. Same recipe as `.landing-kind`.
 */
export default function SearchModeToggle({ mode, onChange, className }: SearchModeToggleProps) {
  return (
    <span
      className={className ? `search-mode ${className}` : "search-mode"}
      role="group"
      aria-label="نوع البحث"
    >
      {MODES.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={mode === option}
          onClick={() => onChange(option)}
        >
          {MODE_LABEL[option]}
        </button>
      ))}
    </span>
  );
}
