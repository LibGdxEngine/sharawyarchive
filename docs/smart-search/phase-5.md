# Phase 5 — Frontend (2026-09-02)

Branch `smart/phase-5-frontend`, stacked on Phase 4. The two-mode search reaches readers: a
«بحث دقيق / بحث ذكي» toggle on the landing box, the site header and the results page, and a smart-mode
results island that asks `POST /api/search/smart/` from the browser.

## What landed

- **Pure libs** (`src/lib/`): `search-mode.ts` (`SearchMode`, `parseSearchMode`, remembered mode
  under `search:mode`, `SEARCH_PLACEHOLDER`, `MODE_LABEL`, `searchHref(q, kind, mode)` — exact-mode
  links look exactly as before); `smart-answer.ts` (the safe parser: paragraphs of `text` / `cite` /
  `ayah` nodes, markers that point at nothing are dropped, no markup is ever interpreted;
  `ayahPlaceholders`); `smart-transport.ts` (`SmartEvent` union, `classifySmartError` — 429 →
  `rate_limited` with `retryAfter`, 404/503 → `unavailable`, 400 → `invalid`, abort → `timeout` — and
  `fetchTransport`, one POST → one event; the Phase 7 streaming seam). `api.ts` gains `smartSearch`
  (with `signal`) and `postSmartFeedback`; `types/models.ts` the `Smart*` types.
- **Hooks** (`src/components/search/`): `useSearchMode` (`useSyncExternalStore`, server snapshot
  `exact`), `useSmartSearch` (reducer over events; one AbortController per question; stage copy on a
  clock at 0 / 4 / 12 s, `slow` at 40 s, client timeout at 60 s; `degraded` is a *ready* state),
  `useAyahTexts` (verse text from `ayah_refs`, else a validated, deduplicated, cached `getAyah`;
  only `text_uthmani` reaches the DOM). `components/player/usePlaySegmentAt` is the "play from here"
  extracted from `ChunkResultList`, with a per-segment cache; `ChunkResultList` now uses it.
- **Components**: `SearchModeToggle` (hook-free, `aria-pressed`, `.search-mode` — the
  `.landing-kind` recipe recoloured per surface), `SearchModeBar` (on `/search`, pushes
  `searchHref`), `SmartResults` (island root, mounted with `key={question}`), `SmartSkeleton`
  (`role="status"` stage line), `SmartStatusBanner`, `SmartErrorNote` (countdown + «تابع بالبحث
  الدقيق»), `SmartAnswer` (chips `aria-controls="cite-N"` that focus the card; badge «إجابة مولّدة
  آليًا»), `AyahInline` (props-only, `.quran-text`, caption «النص القرآني الموثّق — ليس من التفريغ
  الآلي»; `null` renders nothing), `CitationCard` (`id="cite-N"`, `tabIndex=-1`, `data-active`, «نص
  آلي», play + `/listen/{id}?t=`), `PassageList` (always rendered, with the machine-transcript note),
  `SmartFollowups`, `SmartFeedback`, `SmartDisclaimer`.
- **Pages**: `/search?mode=smart` renders the header + `SmartResults` and runs no exact search;
  exact mode is unchanged plus the toggle. The site header keeps `mode=smart` on a re-search and
  switches its placeholder; the landing box carries the toggle next to the kind filter, remembers the
  choice, and submits a hidden `mode` field. `?debug=1` on a staff session shows the API's debug block.
- **CSS** (`globals.css`, appended section): `--color-quran-ink` fallback on `:root` (light + both
  dark selectors), `.search-mode`, `.smart-banner[data-status]`, `.smart-paragraph`,
  `.smart-cite-chip`, `.smart-cite-card[data-active]`, `.smart-cite-number`, `.smart-ayah`.
- **Tests**: `vitest.setup.ts` (testing-library `cleanup`) wired through `setupFiles`;
  `src/test/fetch-stub.ts` (a `fetch` that honours `signal`); `search-mode.test.ts`,
  `smart-answer.test.ts`, `smart-transport.test.ts`, `SearchModeToggle.test.tsx` (pressed state and
  localStorage), `SmartResults.test.tsx` (answer with chips → card focus, the canonical verse and
  never the placeholder, degraded shows passages + marker, stage messages and abort on a new
  question, client timeout, 429 countdown). Frontend: 366 tests, `tsc`, `eslint` and `next build`
  clean.

## Notes

- A verse inside the answer is a `<figure>`, so answer paragraphs are `<div class="smart-paragraph">`
  rather than `<p>` (a `<p>` cannot contain a `<figure>`; the first test run caught the hydration
  warning).
- `make types` (the generated `src/types/api.ts`) was not regenerated here: it needs a running backend
  and nothing imports it. The hand-written `models.ts` is the source the components use.
- Copy: partial «وجدت مقاطع ذات صلة لكن دون إجابة صريحة.», not found «لم أجد في الأرشيف ما يجيب عن
  هذا السؤال…», degraded «تعذّر توليد الإجابة الآن، وهذه أقرب المقاطع لسؤالك.», 429 «وصلت إلى الحد
  المسموح من الأسئلة في هذه الساعة.», unavailable «البحث الذكي غير متاح حاليًا. يمكنك استخدام البحث
  الدقيق.».
