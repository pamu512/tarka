/**
 * Hand validator for server-normalized pack JSON (wire form).
 * ponytail: no ajv yet; mirrors pack.schema.json required fields.
 * `enabled` is frontend-only and must never be required or persisted.
 */

export type ValidatePackResult =
  | { ok: true }
  | { ok: false; errors: string[] };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function checkCondition(c: unknown, path: string, errors: string[]): void {
  if (!isRecord(c)) {
    errors.push(`${path}: condition must be an object`);
    return;
  }
  if (typeof c.field !== "string") errors.push(`${path}.field: required string`);
  if (typeof c.op !== "string") errors.push(`${path}.op: required string`);
}

function checkRule(r: unknown, path: string, errors: string[]): void {
  if (!isRecord(r)) {
    errors.push(`${path}: rule must be an object`);
    return;
  }
  if (typeof r.id !== "string") errors.push(`${path}.id: required string`);
  if (!Array.isArray(r.when)) {
    errors.push(`${path}.when: required array`);
  } else {
    r.when.forEach((c, i) => checkCondition(c, `${path}.when[${i}]`, errors));
  }
  if (!Array.isArray(r.tags)) errors.push(`${path}.tags: required array`);
  if (typeof r.score_delta !== "number") {
    errors.push(`${path}.score_delta: required number`);
  }
  if (typeof r.description !== "string") {
    errors.push(`${path}.description: required string`);
  }
  if (r.when_ast !== undefined && r.when_ast !== null && !isRecord(r.when_ast)) {
    errors.push(`${path}.when_ast: must be object or null`);
  }
}

function checkTagRule(r: unknown, path: string, errors: string[]): void {
  if (!isRecord(r)) {
    errors.push(`${path}: tag_rule must be an object`);
    return;
  }
  if (typeof r.id !== "string") errors.push(`${path}.id: required string`);
  if (!Array.isArray(r.any_tag)) errors.push(`${path}.any_tag: required array`);
  if (!Array.isArray(r.tags)) errors.push(`${path}.tags: required array`);
  if (typeof r.score_delta !== "number") {
    errors.push(`${path}.score_delta: required number`);
  }
  if (typeof r.description !== "string") {
    errors.push(`${path}.description: required string`);
  }
}

export function validatePackJson(input: unknown): ValidatePackResult {
  const errors: string[] = [];
  if (!isRecord(input)) {
    return { ok: false, errors: ["pack must be an object"] };
  }
  if (input.version !== 1) errors.push("version: must be 1");
  if (typeof input.name !== "string" || input.name.length === 0) {
    errors.push("name: required non-empty string");
  }
  if (!Array.isArray(input.rules)) {
    errors.push("rules: required array");
  } else {
    input.rules.forEach((r, i) => checkRule(r, `rules[${i}]`, errors));
  }
  if (input.tag_rules !== undefined) {
    if (!Array.isArray(input.tag_rules)) {
      errors.push("tag_rules: must be an array");
    } else {
      input.tag_rules.forEach((r, i) => checkTagRule(r, `tag_rules[${i}]`, errors));
    }
  }
  if (errors.length) return { ok: false, errors };
  return { ok: true };
}
