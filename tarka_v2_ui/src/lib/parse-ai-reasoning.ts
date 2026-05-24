export type ChainOfThoughtStep = {
  stepIndex: number;
  heading: string;
  body: string;
};

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

const HEADING_MAX = 88;

function truncateHeading(text: string): string {
  const t = text.trim();
  if (!t) return "";
  if (t.length <= HEADING_MAX) return t;
  return `${t.slice(0, HEADING_MAX - 1)}…`;
}

/** Strip leading list markers and markdown bold wrappers from a line used as a title. */
function stripLinePrefix(line: string): string {
  return line
    .replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "")
    .replace(/^\*\*(.+)\*\*$/, "$1")
    .trim();
}

/**
 * Split Shadow markdown `ai_reasoning` into discrete reasoning chunks.
 * Prefers bullet/numbered lines, then paragraph breaks, then single newlines.
 */
export function splitReasoningString(raw: string): string[] {
  const trimmed = raw.trim();
  if (!trimmed) return [];

  const bulletChunks = trimmed
    .split(/\n(?=\s*(?:[-*•]|\d+[.)])\s+)/)
    .map((part) => part.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "").trim())
    .filter(Boolean);
  if (bulletChunks.length > 1) {
    return bulletChunks;
  }

  const paragraphChunks = trimmed
    .split(/\n\s*\n+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (paragraphChunks.length > 1) {
    return paragraphChunks;
  }

  const lineChunks = trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lineChunks.length > 1) {
    return lineChunks;
  }

  return [trimmed];
}

function chunkToStep(chunk: string, stepIndex: number): ChainOfThoughtStep {
  const text = chunk.trim();
  if (!text) {
    return { stepIndex, heading: `Step ${stepIndex + 1}`, body: "" };
  }

  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const firstLine = stripLinePrefix(lines[0] ?? text);
  const heading = truncateHeading(firstLine) || `Step ${stepIndex + 1}`;

  if (lines.length > 1) {
    const body = lines.slice(1).join("\n").trim();
    return { stepIndex, heading, body: body || text };
  }

  return { stepIndex, heading, body: text };
}

function mapArrayItem(item: unknown, stepIndex: number): ChainOfThoughtStep {
  if (typeof item === "string") {
    return chunkToStep(item, stepIndex);
  }

  if (isPlainObject(item)) {
    const title =
      (typeof item.step === "string" && item.step.trim()) ||
      (typeof item.title === "string" && item.title.trim()) ||
      (typeof item.heading === "string" && item.heading.trim()) ||
      `Step ${stepIndex + 1}`;

    const body =
      (typeof item.detail === "string" && item.detail) ||
      (typeof item.text === "string" && item.text) ||
      (typeof item.body === "string" && item.body) ||
      (typeof item.reason === "string" && item.reason) ||
      "";

    return {
      stepIndex,
      heading: truncateHeading(stripLinePrefix(title)) || `Step ${stepIndex + 1}`,
      body: body.length > 0 ? body : JSON.stringify(item, null, 2),
    };
  }

  return {
    stepIndex,
    heading: `Step ${stepIndex + 1}`,
    body:
      item === null || item === undefined
        ? ""
        : typeof item === "number" || typeof item === "boolean"
          ? String(item)
          : JSON.stringify(item),
  };
}

/**
 * Normalizes Shadow `ai_reasoning` into a vertical timeline.
 *
 * - **String** (production Shadow): split on bullets, paragraphs, or newlines.
 * - **Array**: string steps and/or `{ step, detail }` objects (legacy / structured).
 */
export function parseAiReasoning(raw: unknown): ChainOfThoughtStep[] {
  if (raw === null || raw === undefined) {
    return [];
  }

  if (typeof raw === "string") {
    return splitReasoningString(raw).map((chunk, stepIndex) => chunkToStep(chunk, stepIndex));
  }

  if (!Array.isArray(raw)) {
    return [];
  }

  return raw.map((item, stepIndex) => mapArrayItem(item, stepIndex));
}
