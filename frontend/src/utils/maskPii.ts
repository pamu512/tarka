/** Client-side PII masking aligned with integration-ingress ``masked_preview`` (Prompt 177). */

export type PiiFieldKind = "email" | "phone" | "financial" | "generic";

export function maskPiiValue(value: string, kind: PiiFieldKind = "generic"): string {
  const s = (value ?? "").trim();
  if (!s) return "—";
  if (kind === "email" && s.includes("@")) {
    const [local, domain] = s.split("@", 2);
    return `${local.slice(0, 2)}***@${domain}`;
  }
  if (kind === "phone") {
    const digits = s.replace(/\D/g, "");
    if (digits.length >= 4) return `***${digits.slice(-4)}`;
    return "****";
  }
  if (kind === "financial" && s.length > 4) {
    return `****${s.slice(-4)}`;
  }
  if (s.length > 4) {
    return `${s.slice(0, 2)}${"*".repeat(Math.min(8, s.length - 4))}${s.slice(-2)}`;
  }
  return "****";
}

/** SHA-256 hex fingerprint (first 32 chars) — sent to audit API instead of plaintext. */
export async function fingerprintPiiValue(value: string): Promise<string> {
  const data = new TextEncoder().encode(value ?? "");
  const hash = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 32);
}
