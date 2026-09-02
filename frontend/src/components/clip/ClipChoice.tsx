"use client";

/**
 * The chip both clip pickers are made of — output format and visual preset.
 *
 * `aria-pressed` rather than a radio group: these are two-to-three item
 * toggles inside a `fieldset`, and a radio group's arrow-key roving focus in an
 * RTL page buys nothing here that Tab does not already give.
 *
 * `accent` is the one thing the two surfaces disagree on: the verse page marks
 * a selection in its gold, the listen page in the archive ink. Everything else
 * — sizing, the 44px minimum, the pressed semantics — is shared.
 */
export default function ClipChoice({
  selected,
  accent = "var(--color-ink)",
  onClick,
  children,
}: {
  selected: boolean;
  accent?: string;
  onClick(): void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className="flex min-h-11 items-center gap-2 rounded-lg border px-3 py-2 text-xs"
      style={{
        borderColor: selected ? accent : "var(--color-border)",
        color: selected ? "var(--color-ink)" : "var(--color-ink-muted)",
      }}
    >
      {children}
    </button>
  );
}
