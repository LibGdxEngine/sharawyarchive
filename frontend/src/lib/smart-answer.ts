/**
 * Turn `answer_md` into something the UI can render without ever trusting it.
 *
 * The answer is plain Arabic prose carrying two kinds of marker: `[n]`, a
 * citation number, and `[[ayah:S:A]]`, a placeholder for a Quran verse whose
 * text comes from the mushaf, never from the model (rule 1). Everything else
 * is literal text — no markdown, no HTML. A marker that points at nothing
 * (a citation number the response does not have, an ayah that is not in
 * `ayah_refs`) is dropped rather than shown.
 */

export type AnswerNode =
  | { type: "text"; text: string }
  | { type: "cite"; n: number }
  | { type: "ayah"; surah: number; ayah: number };

export interface AnswerParagraph {
  nodes: AnswerNode[];
}

export interface ParseOptions {
  /** How many citations the response carries; `[n]` beyond it is dropped. */
  citationCount: number;
  /** `"S:A"` keys of the ayahs the response hydrated. */
  ayahKeys: ReadonlySet<string>;
}

const MARKER = /\[(\d{1,3})\]|\[\[ayah:(\d{1,3}):(\d{1,4})\]\]/g;

export function ayahKey(surah: number, ayah: number): string {
  return `${surah}:${ayah}`;
}

function pushText(nodes: AnswerNode[], text: string): void {
  if (text === "") return;
  const last = nodes[nodes.length - 1];
  if (last !== undefined && last.type === "text") {
    last.text += text;
  } else {
    nodes.push({ type: "text", text });
  }
}

function parseParagraph(line: string, options: ParseOptions): AnswerParagraph {
  const nodes: AnswerNode[] = [];
  let cursor = 0;
  for (const match of line.matchAll(MARKER)) {
    const index = match.index ?? 0;
    pushText(nodes, line.slice(cursor, index));
    cursor = index + match[0].length;
    if (match[1] !== undefined) {
      const n = Number(match[1]);
      if (n >= 1 && n <= options.citationCount) nodes.push({ type: "cite", n });
      continue;
    }
    const surah = Number(match[2]);
    const ayah = Number(match[3]);
    if (options.ayahKeys.has(ayahKey(surah, ayah))) {
      nodes.push({ type: "ayah", surah, ayah });
    }
  }
  pushText(nodes, line.slice(cursor));
  // A dropped marker can leave two spaces behind; readers should not see them.
  for (const node of nodes) {
    if (node.type === "text") node.text = node.text.replace(/ {2,}/g, " ");
  }
  return { nodes };
}

/** Paragraphs (split on newlines) of typed nodes; blank lines vanish. */
export function parseAnswer(markdown: string, options: ParseOptions): AnswerParagraph[] {
  return markdown
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "")
    .map((line) => parseParagraph(line, options))
    .filter((paragraph) => paragraph.nodes.length > 0);
}

/** Every `[[ayah:S:A]]` placeholder in the text, in order, each once. */
export function ayahPlaceholders(markdown: string): { surah: number; ayah: number }[] {
  const seen = new Set<string>();
  const refs: { surah: number; ayah: number }[] = [];
  for (const match of markdown.matchAll(/\[\[ayah:(\d{1,3}):(\d{1,4})\]\]/g)) {
    const surah = Number(match[1]);
    const ayah = Number(match[2]);
    const key = ayahKey(surah, ayah);
    if (seen.has(key)) continue;
    seen.add(key);
    refs.push({ surah, ayah });
  }
  return refs;
}
