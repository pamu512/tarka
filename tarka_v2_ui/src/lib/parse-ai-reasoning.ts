export type ChainOfThoughtStep = {
  stepIndex: number;
  heading: string;
  body: string;
};

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

/**
 * Normalizes orchestrator `ai_reasoning` payloads into a vertical timeline.
 * Accepts string steps and/or objects with step/title/heading + text/detail/body/reason.
 */
export function parseAiReasoning(raw: unknown): ChainOfThoughtStep[] {
  if (!Array.isArray(raw)) return [];

  return raw.map((item, stepIndex) => {
    if (typeof item === "string") {
      const body = item.trim();
      const firstLine = body.split(/\r?\n/)[0]?.trim() ?? body;
      const heading =
        firstLine.length > 0
          ? firstLine.length > 88
            ? `${firstLine.slice(0, 85)}…`
            : firstLine
          : `Step ${stepIndex + 1}`;
      return { stepIndex, heading, body: body || heading };
    }

    if (isPlainObject(item)) {
      const title =
        (typeof item.step === "string" && item.step) ||
        (typeof item.title === "string" && item.title) ||
        (typeof item.heading === "string" && item.heading) ||
        `Step ${stepIndex + 1}`;

      const body =
        (typeof item.text === "string" && item.text) ||
        (typeof item.detail === "string" && item.detail) ||
        (typeof item.body === "string" && item.body) ||
        (typeof item.reason === "string" && item.reason) ||
        "";

      return {
        stepIndex,
        heading: title,
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
  });
}
