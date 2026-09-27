export type TranscriptEntry = {
  time: string | null;
  speaker: string | null;
  text: string;
};

const LEGACY_LINE = /^\[(\d{2}:\d{2}:\d{2})(?:\s+([^\]]+))?\]\s*(.*)$/;

export function parseTranscript(input: string): TranscriptEntry[] {
  const normalized = input.replace(/\r\n?/g, "\n").trim();
  if (!normalized) return [];

  const lines = normalized.split("\n");
  const legacy: TranscriptEntry[] = [];
  let buffer: string[] = [];

  const flush = () => {
    const text = buffer.join("\n").trim();
    if (text) legacy.push({ time: null, speaker: null, text });
    buffer = [];
  };

  for (const line of lines) {
    const match = line.trim().match(LEGACY_LINE);
    if (match) {
      flush();
      legacy.push({
        time: match[1],
        speaker: match[2]?.trim() || null,
        text: match[3].trim(),
      });
    } else {
      buffer.push(line);
    }
  }
  flush();

  if (legacy.some((entry) => entry.time))
    return legacy.filter((entry) => entry.text);
  return normalized
    .split(/\n\s*\n+/)
    .map((text) => ({ time: null, speaker: null, text: text.trim() }))
    .filter((entry) => entry.text);
}
