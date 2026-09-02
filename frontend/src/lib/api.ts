import { pickChunkForWord } from "@/lib/correction-selection";
import type {
  Surah,
  SurahDetail,
  AyahDetail,
  QuranLocation,
  Segment,
  SegmentChunk,
  Transcript,
  SearchResponse,
  Topic,
  TopicDetail,
  CorrectionResponse,
  ClipCreateResponse,
  Clip,
  SmartFeedbackPayload,
  SmartFeedbackResponse,
  SmartFilters,
  SmartResponse,
} from "@/types/models";

const BASE_URL = (
  typeof window === "undefined"
    ? (process.env.BACKEND_API_URL ??
      process.env.NEXT_PUBLIC_API_URL ??
      "http://localhost:8000/api")
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api")
).replace(/\/$/, "");

/**
 * A non-2xx API response.
 *
 * Carries the status so callers can tell apart the cases the UI has words for
 * — 429 (throttled) and 404 (endpoint or object missing) — from a generic
 * failure. Extends Error, so existing `catch {}` sites are unaffected.
 */
export class ApiError extends Error {
  readonly status: number;
  /**
   * Seconds until the request is worth repeating, from `Retry-After`. Only DRF
   * throttles set it (429), and only same-origin callers can read it — which is
   * every browser caller here, since Caddy serves `/api/*` on the site origin.
   */
  readonly retryAfter: number | null;

  constructor(status: number, path: string, retryAfter: number | null = null) {
    super(`API ${status}: ${path}`);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

/** Absolute URL of an API path, for callers that cannot go through apiFetch. */
export function apiUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

/** `Retry-After` as whole seconds, or null when absent or an HTTP-date. */
export function parseRetryAfter(res: Response): number | null {
  const raw = res.headers.get("Retry-After");
  if (raw === null) return null;
  const seconds = Number.parseInt(raw, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "Accept-Encoding": "gzip",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new ApiError(res.status, path, parseRetryAfter(res));
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Surahs
// ---------------------------------------------------------------------------

export function getSurahs(): Promise<Surah[]> {
  return apiFetch<Surah[]>("/surahs/");
}

export function getSurah(n: number, page = 1): Promise<SurahDetail> {
  return apiFetch<SurahDetail>(`/surahs/${n}/?page=${page}`);
}

// ---------------------------------------------------------------------------
// Ayahs
// ---------------------------------------------------------------------------

export function getAyah(surah: number, ayah: number): Promise<AyahDetail> {
  return apiFetch<AyahDetail>(`/ayahs/${surah}/${ayah}/`);
}

/**
 * Where a mushaf page or juz begins — exactly one of them, per the endpoint.
 *
 * Throws `ApiError` with status 404 when the page or juz is past the end of
 * the mushaf, which the index treats as "that reference goes nowhere".
 */
export function locate(
  target: { page: number } | { juz: number }
): Promise<QuranLocation> {
  const query =
    "page" in target ? `page=${target.page}` : `juz=${target.juz}`;
  return apiFetch<QuranLocation>(`/quran/locate/?${query}`);
}

// ---------------------------------------------------------------------------
// Segments
// ---------------------------------------------------------------------------

export function getSegment(id: number): Promise<Segment> {
  return apiFetch<Segment>(`/segments/${id}/`);
}

/**
 * Chunk map of a segment — word ranges paired with the chunk ids corrections
 * are filed against. Throws ApiError(404) where the deployment predates the
 * endpoint, which the correction UI reports as "unavailable" rather than an
 * error.
 */
export function getSegmentChunks(id: number): Promise<SegmentChunk[]> {
  return apiFetch<SegmentChunk[]>(`/segments/${id}/chunks/`);
}

/**
 * A transcript, addressed by `?v=` so a corrected one arrives under a new URL.
 *
 * `store: false` opts the request out of Next's fetch cache, for the server
 * render of /listen: the payload is tens of kilobytes per segment across four
 * thousand segments, and the backend is a same-cluster hop away, so caching it
 * on the server trades a lot of disk for very little latency. In the browser
 * the default path is the one that matters — the HTTP cache and the service
 * worker both key off the versioned URL.
 */
export function getTranscript(
  id: number,
  version?: number,
  { store = true }: { store?: boolean } = {}
): Promise<Transcript> {
  const qs = version !== undefined ? `?v=${version}` : "";
  return apiFetch<Transcript>(
    `/segments/${id}/transcript/${qs}`,
    (store
      ? { next: { revalidate: false }, cache: "force-cache" }
      : { cache: "no-store" }) as RequestInit
  );
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

export interface SearchParams {
  q: string;
  kind?: "recitation" | "khawatir";
  surah?: number;
  page?: number;
}

export function search(params: SearchParams): Promise<SearchResponse> {
  const sp = new URLSearchParams({ q: params.q });
  if (params.kind) sp.set("kind", params.kind);
  if (params.surah !== undefined) sp.set("surah", String(params.surah));
  if (params.page !== undefined) sp.set("page", String(params.page));
  return apiFetch<SearchResponse>(`/search/?${sp.toString()}`);
}

// ---------------------------------------------------------------------------
// Smart search
// ---------------------------------------------------------------------------

export interface SmartSearchOptions {
  signal?: AbortSignal;
  filters?: SmartFilters;
  /** Honoured by the API for staff sessions only. */
  debug?: boolean;
}

/**
 * Ask the archive a question (API_CONTRACT.md amendment 15).
 *
 * Runs for up to 40 s server-side, so callers pass an AbortSignal and must be
 * client-side — a server render waiting on this would hold the whole route.
 * Throws ApiError: 429 (rate or concurrency cap, with `retryAfter`), 503
 * (feature off), 400 (bad question).
 */
export function smartSearch(
  question: string,
  { signal, filters, debug }: SmartSearchOptions = {}
): Promise<SmartResponse> {
  const body: Record<string, unknown> = { question };
  if (filters !== undefined) body.filters = filters;
  if (debug) body.debug = true;
  return apiFetch<SmartResponse>("/search/smart/", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}

export function postSmartFeedback(
  queryId: string,
  payload: SmartFeedbackPayload
): Promise<SmartFeedbackResponse> {
  return apiFetch<SmartFeedbackResponse>(`/search/smart/${queryId}/feedback/`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Topics
// ---------------------------------------------------------------------------

export function getTopics(): Promise<Topic[]> {
  return apiFetch<Topic[]>("/topics/");
}

export function getTopic(slug: string): Promise<TopicDetail> {
  return apiFetch<TopicDetail>(`/topics/${slug}/`);
}

// ---------------------------------------------------------------------------
// Corrections
// ---------------------------------------------------------------------------

export interface CorrectionPayload {
  chunk_id: number;
  word_start: number;
  word_end: number;
  suggested_text: string;
}

export function postCorrection(
  payload: CorrectionPayload
): Promise<CorrectionResponse> {
  return apiFetch<CorrectionResponse>("/corrections/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Submit a correction for a word range of a segment.
 *
 * The transcript view knows word indices; the corrections endpoint is keyed by
 * `chunk_id`. This resolves the gap by reading the segment's chunk map first
 * and posting against the chunk that owns `wordStart`.
 *
 * Throws ApiError — 404 when the chunk map is missing or empty, 429 when the
 * IP throttle has tripped.
 */
export async function postCorrectionForWords(
  segmentId: number,
  wordStart: number,
  wordEnd: number,
  suggestedText: string
): Promise<CorrectionResponse> {
  const chunks = await getSegmentChunks(segmentId);
  const chunk = pickChunkForWord(chunks, wordStart);
  if (chunk === null) {
    throw new ApiError(404, `/segments/${segmentId}/chunks/`);
  }
  return postCorrection({
    chunk_id: chunk.chunk_id,
    word_start: wordStart,
    word_end: wordEnd,
    suggested_text: suggestedText,
  });
}

// ---------------------------------------------------------------------------
// Clips
// ---------------------------------------------------------------------------

export interface ClipPayload {
  segment_id: number;
  start_ms: number;
  end_ms: number;
  preset: string;
  /** "video" (the default) or "audio". */
  output?: "video" | "audio";
}

export function createClip(payload: ClipPayload): Promise<ClipCreateResponse> {
  return apiFetch<ClipCreateResponse>("/clips/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getClip(id: string): Promise<Clip> {
  return apiFetch<Clip>(`/clips/${id}/`);
}
