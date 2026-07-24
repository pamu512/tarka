/** Shared mock API types and helpers (used by mockData.ts and feature slices). */
export type AnyObj = Record<string, unknown>;

/** Alphanumeric suffix for demo IDs — Web Crypto, not Math.random (CodeQL js/insecure-randomness). */
export function mockRandomAlpha(length: number): string {
  const g = globalThis.crypto;
  if (!g?.getRandomValues) {
    throw new Error("Web Crypto API required for mock id generation");
  }
  const buf = new Uint8Array(length);
  g.getRandomValues(buf);
  const alphabet = "0123456789abcdefghijklmnopqrstuvwxyz";
  let s = "";
  for (let i = 0; i < length; i++) {
    s += alphabet[buf[i]! % alphabet.length]!;
  }
  return s;
}
