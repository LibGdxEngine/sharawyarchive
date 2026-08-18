/**
 * Which elements own the keyboard, and which leave it to the transport.
 */

/**
 * Marks a transcript word button (set in TranscriptView).
 *
 * Every word in a transcript is a button, and a button is normally something
 * that answers Space itself. These ones must not: after one click to seek, the
 * word keeps focus, and the reader who then presses Space means "pause", not
 * "seek to this word again".
 */
export const TRANSCRIPT_WORD_ATTRIBUTE = "data-transcript-word";

/**
 * True when a keydown on this target belongs to the element — text being typed,
 * or a control that already owns these keys — and not to the app-wide media
 * transport.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.hasAttribute(TRANSCRIPT_WORD_ATTRIBUTE)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    tag === "BUTTON" ||
    tag === "A"
  );
}
