export interface SubtitleWord {
  start: number;
  end: number;
  text: string;
}

export interface SubtitleCue {
  start: number;
  end: number;
  text: string;
  words?: SubtitleWord[];
  wordTimingSource?: "inline";
}

const INLINE_TIMESTAMP = /<((?:\d{1,3}:)?\d{1,2}:\d{2}[.,]\d{1,3})>/g;
const HTML_ENTITY = /&(?:amp|lt|gt|quot|apos|nbsp|#\d+|#x[\da-f]+);/gi;
const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

export function decodeSubtitleEntities(value: string): string {
  return value.replace(HTML_ENTITY, (entity) => {
    const body = entity.slice(1, -1);
    const named = NAMED_ENTITIES[body.toLowerCase()];
    if (named) return named;
    const codePoint = body.toLowerCase().startsWith("#x")
      ? Number.parseInt(body.slice(2), 16)
      : Number.parseInt(body.slice(1), 10);
    return Number.isFinite(codePoint) ? String.fromCodePoint(codePoint) : entity;
  });
}

/** Keep captions as one text flow; the browser decides where the box wraps. */
export function subtitleDisplayText(value: string): string {
  const decoded = decodeSubtitleEntities(value)
    .replace(/<[^>]*>/g, "")
    .replace(/[\r\n]+/g, " ")
    .replace(/[ \t]+/g, " ")
    .trim();
  return decoded.replace(/(?:^|\s)>>(?=\s|$)/g, " ").replace(/[ \t]+/g, " ").trim();
}

function toSeconds(value: string): number {
  const parts = value.trim().replace(",", ".").split(":");
  let seconds = 0;
  for (const part of parts) seconds = seconds * 60 + Number.parseFloat(part);
  return Number.isFinite(seconds) ? seconds : 0;
}

function addTimedWords(
  words: SubtitleWord[],
  value: string,
  start: number,
  end: number,
): boolean {
  const text = subtitleDisplayText(value);
  if (!text) return true;
  const parts = text.split(" ").filter(Boolean);
  // Do not invent per-word timing for a multi-word segment between two
  // timestamps. The caller will fall back to cue-level emphasis instead.
  if (parts.length !== 1) return false;
  words.push({ text: parts[0]!, start, end: Math.max(start, end) });
  return true;
}

/** Preserve YouTube's inline word timestamps when the source track provides them. */
export function parseInlineWordTimeline(
  rawText: string,
  cueStart: number,
  cueEnd: number,
): SubtitleWord[] {
  const decoded = decodeSubtitleEntities(rawText);
  const matches = Array.from(decoded.matchAll(INLINE_TIMESTAMP));
  if (matches.length === 0) return [];
  const words: SubtitleWord[] = [];
  let cursor = 0;
  let segmentStart = cueStart;
  let exact = true;
  for (const match of matches) {
    const index = match.index ?? cursor;
    const segmentEnd = Math.min(cueEnd, Math.max(cueStart, toSeconds(match[1] ?? "0")));
    exact = addTimedWords(words, decoded.slice(cursor, index), segmentStart, segmentEnd) && exact;
    segmentStart = segmentEnd;
    cursor = index + match[0].length;
  }
  exact = addTimedWords(words, decoded.slice(cursor), segmentStart, cueEnd) && exact;
  return exact ? words : [];
}

export function parseSubtitles(raw: string): SubtitleCue[] {
  const text = raw.replace(/^\uFEFF/, "").replace(/^WEBVTT[^\n]*(?:\r?\n){1,2}/i, "");
  const blocks = text.trim().split(/\r?\n\s*\r?\n/);
  const cues: SubtitleCue[] = [];
  for (const block of blocks) {
    const lines = block.split(/\r?\n/).filter((line) => line.trim().length > 0);
    const timingIndex = lines.findIndex((line) => line.includes("-->"));
    if (timingIndex < 0) continue;
    const timing = lines[timingIndex]?.match(/([\d:.,]+)\s*-->\s*([\d:.,]+)/);
    if (!timing) continue;
    const start = toSeconds(timing[1] ?? "0");
    const end = toSeconds(timing[2] ?? "0");
    const rawCueText = lines.slice(timingIndex + 1).join(" ");
    const textValue = subtitleDisplayText(rawCueText);
    if (!textValue) continue;
    const words = parseInlineWordTimeline(rawCueText, start, end);
    cues.push({
      start,
      end,
      text: textValue,
      ...(words.length ? { words, wordTimingSource: "inline" as const } : {}),
    });
  }
  return cues.sort((left, right) => left.start - right.start);
}
