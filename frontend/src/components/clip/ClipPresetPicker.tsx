"use client";

import ClipChoice from "./ClipChoice";
import { CLIP_THEMES } from "./ClipPreview";
import type { ClipTheme } from "./ClipPreview";

/**
 * "النمط" — the look of the rendered card.
 *
 * One picker for both clip UIs, over the preview themes rather than the
 * backend's preset ids: the swatch has to match what {@link ClipPreview} draws,
 * and `CLIP_THEME_PRESET` maps the choice back to the id the API wants.
 */
export default function ClipPresetPicker({
  theme,
  setTheme,
  accent,
}: {
  theme: ClipTheme;
  setTheme(next: ClipTheme): void;
  accent?: string;
}) {
  return (
    <fieldset>
      <legend className="text-xs text-[var(--color-ink-faint)]">النمط</legend>
      <div className="mt-2 flex flex-wrap gap-3">
        {CLIP_THEMES.map((option) => (
          <ClipChoice
            key={option.id}
            selected={option.id === theme.id}
            accent={accent}
            onClick={() => setTheme(option)}
          >
            <span
              aria-hidden="true"
              className="flex h-6 w-4 flex-col justify-end gap-0.5 p-0.5"
              style={{ background: option.swatchBg }}
            >
              <span
                className="block h-0.5 w-full"
                style={{ backgroundColor: option.swatchInk }}
              />
              <span
                className="block h-0.5 w-2/3"
                style={{ backgroundColor: option.swatchInk }}
              />
            </span>
            {option.label}
          </ClipChoice>
        ))}
      </div>
    </fieldset>
  );
}
