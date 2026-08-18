/**
 * Site identity — the single source for the public origin and name.
 *
 * `NEXT_PUBLIC_SITE_URL` is what metadataBase, canonical URLs and the clip
 * attribution line all resolve against. It falls back to localhost so a build
 * without the variable still produces valid absolute URLs instead of failing.
 */

export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"
).replace(/\/$/, "");

export const SITE_NAME = "أرشيف الشعراوي";

/** Bare host of {@link SITE_URL}, for attribution text. */
export function siteHost(): string {
  try {
    return new URL(SITE_URL).host;
  } catch {
    return SITE_URL;
  }
}
