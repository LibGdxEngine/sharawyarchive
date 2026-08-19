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

export interface SearchResponse {
  query: string;
  mode: "hybrid" | "lexical" | "semantic";
  ayah_matches: AyahMatch[];
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
  video_url: string | null;
}
