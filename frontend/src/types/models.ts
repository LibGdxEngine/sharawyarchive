// ---------------------------------------------------------------------------
// API response types — mirrors API_CONTRACT.md exactly
// All timestamps are integer milliseconds.
// ---------------------------------------------------------------------------

export interface Surah {
  number: number;
  name_ar: string;
  name_ar_plain: string;
  name_en: string;
  ayah_count: number;
  revelation_place: string;
  segment_count: number;
  /** Inclusive juz span of the surah's ayahs. */
  juz_start: number;
  juz_end: number;
  /** Inclusive Madani-mushaf page span of the surah's ayahs. */
  page_start: number;
  page_end: number;
}

/** `GET /api/quran/locate/` — where a mushaf page or juz begins. */
export interface QuranLocation {
  surah: number;
  number: number;
  surah_name_ar: string;
  juz: number;
  page: number;
}

export interface AyahSummary {
  number: number;
  text_uthmani: string;
  juz: number;
  page: number;
  sajda: boolean;
  segment_count: number;
}

export interface PaginatedAyahs {
  count: number;
  page: number;
  page_size: number;
  results: AyahSummary[];
}

export interface SurahDetail {
  number: number;
  name_ar: string;
  name_en: string;
  ayah_count: number;
  revelation_place: string;
  ayahs: PaginatedAyahs;
}

export interface SegmentSummary {
  id: number;
  kind: "recitation" | "khawatir";
  title: string;
  ayah_start: number;
  ayah_end: number;
  duration_ms: number;
}

export interface AyahDetail {
  surah: number;
  number: number;
  text_uthmani: string;
  text_imlaei: string;
  juz: number;
  page: number;
  segments: SegmentSummary[];
}

export interface Source {
  title: string;
  kind: string;
}

export interface Segment {
  id: number;
  kind: "recitation" | "khawatir";
  title: string;
  surah: number;
  ayah_start: number;
  ayah_end: number;
  duration_ms: number;
  ordinal: number;
  audio_url: string;
  waveform_url: string;
  source: Source;
  /** Null until the segment has been transcribed. */
  transcript_version: number | null;
  is_human_reviewed: boolean;
}

/**
 * Compact transcript word — keys intentionally short for network efficiency.
 * i = index, t = text, s = start_ms, e = end_ms, c = confidence
 *
 * `c` is null for a word that came from a human correction rather than the
 * recogniser: there is no model confidence to report for text a person wrote.
 */
export interface TranscriptWord {
  i: number;
  t: string;
  s: number;
  e: number;
  c: number | null;
}

export interface Transcript {
  version: number;
  engine: string;
  is_human_reviewed: boolean;
  words: TranscriptWord[];
}

/**
 * One transcript chunk of a segment, from GET /api/segments/{id}/chunks/.
 *
 * The bridge between the transcript view and POST /api/corrections/: the
 * transcript payload carries word indices only, while a correction is filed
 * against a `chunk_id`, so the UI resolves the owning chunk from this list.
 */
export interface SegmentChunk {
  chunk_id: number;
  start_ms: number;
  end_ms: number;
  /** First word index of the chunk, into the transcript word array.
   *  Null for a degenerate chunk whose span holds no aligned words. */
  word_start: number | null;
  /** Last word index of the chunk, inclusive. Null like `word_start`. */
  word_end: number | null;
}

/** Precomputed waveform, served as JSON from `Segment.waveform_url`. */
export interface Waveform {
  /** Amplitude per bucket, normalized to 0..1. */
  peaks: number[];
  duration_ms: number;
}

/**
 * The search-result shape, reused by /topics/{slug} and /segments/{id}/related/.
 *
 * `surah` and the ayah range are null for a chunk the pipeline could not place
 * against the mushaf — a khawatir aside, an introduction — so the citation line
 * is omitted rather than printed with holes in it.
 */
export interface SearchChunkResult {
  chunk_id: number;
  segment_id: number;
  segment_title: string;
  surah: number | null;
  ayah_start: number | null;
  ayah_end: number | null;
  kind: "recitation" | "khawatir";
  text: string;
  start_ms: number;
  end_ms: number;
}

export interface AyahMatch {
  surah: number;
  number: number;
  text_uthmani: string;
  surah_name_ar: string;
}

/**
 * A canonical mushaf verse found by full-text search over the Quran text itself
 * (not a reference parsed from the query — that is `AyahMatch`).
 */
export interface VerseMatch {
  surah: number;
  number: number;
  text_uthmani: string;
  surah_name_ar: string;
  juz: number;
  page: number;
}

export interface SearchResponse {
  query: string;
  ayah_matches: AyahMatch[];
  verse_matches: VerseMatch[];
  results: SearchChunkResult[];
  page: number;
  total: number;
}

export interface Topic {
  slug: string;
  name_ar: string;
  description_ar: string;
  chunk_count: number;
}

export interface TopicDetail {
  slug: string;
  name_ar: string;
  description_ar: string;
  chunk_count: number;
  chunks: SearchChunkResult[];
}

export interface CorrectionResponse {
  id: number;
  status: "pending";
}

export type ClipStatus = "queued" | "rendering" | "done" | "failed";

/** What a clip job produces: a video card or a plain audio export. */
export type ClipOutput = "video" | "audio";

/**
 * POST /api/clips/. A fresh job answers 202 "queued", but an identical range
 * already on file answers 200 with whatever that clip's status is by now — so
 * the create response carries the full status union, not just "queued".
 */
export interface ClipCreateResponse {
  id: string;
  status: ClipStatus;
}

export interface Clip {
  id: string;
  status: ClipStatus;
  output: ClipOutput;
  /** Presigned bucket URL, expires in hours. Prefer {@link Clip.media_url}. */
  video_url: string | null;
  /** Presigned bucket URL, expires in hours. Prefer {@link Clip.media_url}. */
  audio_url: string | null;
  /**
   * Same-origin address of the rendered bytes, whichever output this job
   * produced. It re-signs the bucket object per request, so unlike the two
   * presigned URLs above it is safe to embed in a shared page or an OpenGraph
   * card. Null until the render is `done`.
   */
  media_url: string | null;
  /**
   * The same bytes served as an attachment. A bare `<a download>` pointing at
   * the bucket is ignored by the browser — different origin — so this is the
   * only address that actually saves a file.
   */
  download_url: string | null;
  /** The Arabic name the browser will save {@link Clip.download_url} under. */
  download_filename: string | null;
}

// ---------------------------------------------------------------------------
// Smart search (API_CONTRACT.md amendment 15)
// ---------------------------------------------------------------------------

export type SmartStatus = "answered" | "partial" | "not_found" | "degraded";

/**
 * One verified quote: the milliseconds are those of the transcript words it
 * spans, and `quote_display` is machine-transcript text — shown only with the
 * «نص آلي» marker.
 */
export interface SmartCitation {
  n: number;
  passage_id: number;
  chunk_id: number | null;
  segment_id: number;
  segment_title: string;
  surah: number | null;
  ayah_start: number | null;
  ayah_end: number | null;
  start_ms: number;
  end_ms: number;
  quote_display: string;
  listen_url: string;
}

export interface SmartPassage {
  passage_id: number;
  chunk_id: number | null;
  segment_id: number;
  segment_title: string;
  surah: number | null;
  ayah_start: number | null;
  ayah_end: number | null;
  start_ms: number;
  end_ms: number;
  excerpt_display: string;
  score: number;
}

/** Canonical verse text from the quran app — the only text that may render as Quran. */
export interface SmartAyah {
  surah: number;
  ayah: number;
  surah_name_ar: string;
  text_uthmani: string;
}

export interface SmartResponse {
  query_id: string;
  mode: "smart";
  status: SmartStatus;
  /** Arabic prose with `[n]` citation markers and `[[ayah:S:A]]` placeholders; null when degraded. */
  answer_md: string | null;
  citations: SmartCitation[];
  passages: SmartPassage[];
  ayah_refs: SmartAyah[];
  followups: string[];
  cache_hit: boolean;
  debug: Record<string, unknown> | null;
}

export interface SmartFilters {
  surah?: number;
  source_id?: number;
}

export interface SmartFeedbackPayload {
  vote: "up" | "down";
  note?: string;
}

export interface SmartFeedbackResponse {
  status: "recorded";
}
