import { amiriFont } from "@/fonts";
import ListenSkeleton from "@/components/player/ListenSkeleton";

/*
 * Route-level skeleton for /listen/[segmentId].
 *
 * The route is force-dynamic, so without this boundary a click on "استمع" left
 * the previous page on screen — with no sign a navigation had started — until
 * the server had answered and the page had hydrated. The wrapper repeats
 * page.tsx's `.listen-page` + Amiri scope so the gold tokens and the classical
 * face are already in place when the real page swaps in.
 */
export default function Loading() {
  return (
    <main className={`listen-page ${amiriFont.variable}`}>
      <ListenSkeleton />
    </main>
  );
}
