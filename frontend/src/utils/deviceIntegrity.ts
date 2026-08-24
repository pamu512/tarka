/**
 * Investigator first-open: native device integrity (rooted / jailbroken / biometrics).
 * Never invent a value. If a field is absent, the strip still shows "missing".
 * Do not treat always-false client fields (e.g. is_spoofed_location) as real.
 */

export const DEVICE_INTEGRITY_MISSING = "missing";

export type IntegrityTriState = "yes" | "no" | typeof DEVICE_INTEGRITY_MISSING;

export type DeviceIntegrityView = {
  rooted: IntegrityTriState;
  jailbroken: IntegrityTriState;
  biometrics: IntegrityTriState;
};

export type DeviceIntegritySource = {
  tags?: readonly string[] | null;
  top_signals?: readonly string[] | null;
  device_context?: Record<string, unknown> | null;
  evaluate_payload?: Record<string, unknown> | null;
  integrity?: Record<string, unknown> | null;
};

export type IntegrityPresence = "true" | "present" | typeof DEVICE_INTEGRITY_MISSING;

export type IntegrityPresenceView = {
  rooted: IntegrityPresence;
  jailbroken: IntegrityPresence;
  biometrics: IntegrityPresence;
};

const TAG_ROOTED = "sdk:rooted";
const TAG_JAILBROKEN = "sdk:jailbroken";
const TAG_BIOMETRICS = "sdk:biometrics";

function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function readBool(v: unknown): boolean | undefined {
  return typeof v === "boolean" ? v : undefined;
}

function deviceContextFrom(input: DeviceIntegritySource): Record<string, unknown> | null {
  const fromDirect = asRecord(input.device_context);
  if (fromDirect) return fromDirect;
  const ep = asRecord(input.evaluate_payload);
  if (!ep) return null;
  return asRecord(ep.device_context) ?? asRecord(ep.deviceContext);
}

function signalsFrom(dc: Record<string, unknown> | null): Record<string, unknown> | null {
  if (!dc) return null;
  return asRecord(dc.signals);
}

function tagHit(tags: ReadonlySet<string>, tag: string): boolean {
  return tags.has(tag);
}

function triState(booleanValue: boolean | undefined, tagged: boolean): IntegrityTriState {
  if (booleanValue === true) return "yes";
  if (booleanValue === false) return "no";
  if (tagged) return "yes";
  return DEVICE_INTEGRITY_MISSING;
}

/**
 * Resolve rooted / jailbroken / biometrics from device_context, tags, and inference top_signals.
 * Tags only confirm true. A stored boolean is required to show no.
 */
export function resolveDeviceIntegrity(input: DeviceIntegritySource): DeviceIntegrityView {
  const dc = deviceContextFrom(input);
  const signals = signalsFrom(dc);
  const tagList = [...(input.tags ?? []), ...(input.top_signals ?? [])].filter(
    (t): t is string => typeof t === "string" && t.length > 0,
  );
  const tags = new Set(tagList);

  return {
    rooted: triState(readBool(signals?.is_rooted), tagHit(tags, TAG_ROOTED)),
    jailbroken: triState(readBool(signals?.is_jailbroken), tagHit(tags, TAG_JAILBROKEN)),
    biometrics: triState(readBool(signals?.has_biometrics), tagHit(tags, TAG_BIOMETRICS)),
  };
}

function asPresence(v: unknown): IntegrityPresence | null {
  return v === "true" || v === "present" || v === DEVICE_INTEGRITY_MISSING ? v : null;
}

function derivePresence(booleanValue: boolean | undefined, tagged: boolean): IntegrityPresence {
  if (booleanValue === true || tagged) return "true";
  if (booleanValue === false) return "present";
  return DEVICE_INTEGRITY_MISSING;
}

/**
 * Decision-row / FLAG labels: present | missing | true.
 * Never invent false for omitted jailbreak / biometrics / root.
 */
export function resolveIntegrityPresence(input: DeviceIntegritySource): IntegrityPresenceView {
  const fromMap =
    asRecord(input.integrity) ??
    asRecord(asRecord(input.evaluate_payload)?.integrity) ??
    asRecord(deviceContextFrom(input)?.integrity);
  const dc = deviceContextFrom(input);
  const signals = signalsFrom(dc) ?? signalsFrom(fromMap);
  const tagList = [...(input.tags ?? []), ...(input.top_signals ?? [])].filter(
    (t): t is string => typeof t === "string" && t.length > 0,
  );
  const tags = new Set(tagList);

  return {
    rooted:
      asPresence(fromMap?.is_rooted) ??
      derivePresence(readBool(signals?.is_rooted), tagHit(tags, TAG_ROOTED)),
    jailbroken:
      asPresence(fromMap?.is_jailbroken) ??
      derivePresence(readBool(signals?.is_jailbroken), tagHit(tags, TAG_JAILBROKEN)),
    biometrics:
      asPresence(fromMap?.has_biometrics) ??
      derivePresence(readBool(signals?.has_biometrics), tagHit(tags, TAG_BIOMETRICS)),
  };
}
