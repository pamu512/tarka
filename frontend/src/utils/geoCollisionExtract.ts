/** Approximate geographic centers for IP vs ship-to country fallback (ISO 3166-1 alpha-2). */
export const ISO2_CENTROID: Record<string, [number, number]> = {
  US: [39.8283, -98.5795],
  GB: [54.7024, -3.2766],
  DE: [51.1657, 10.4515],
  FR: [46.6034, 1.8883],
  CA: [61.0667, -107.9917],
  AU: [-24.7761, 134.755],
  BR: [-14.235, -51.9253],
  IN: [22.3511, 78.6677],
  JP: [36.2048, 138.2529],
  MX: [23.6345, -102.5528],
  NL: [52.1326, 5.2913],
  ES: [40.4637, -3.7492],
  IT: [41.8719, 12.5674],
  PL: [51.9194, 19.1451],
  TR: [38.9637, 35.2433],
  AR: [-38.4161, -63.6167],
  CO: [4.5709, -74.2973],
  NG: [9.082, 8.6753],
  ZA: [-30.5595, 22.9375],
  KR: [35.9078, 127.7669],
  TW: [23.6978, 120.9605],
  HK: [22.3193, 114.1694],
  SG: [1.3521, 103.8198],
  AE: [23.4241, 53.8478],
  IE: [53.4129, -8.2439],
  PT: [39.3999, -8.2245],
  SE: [60.1282, 18.6435],
  CH: [46.8182, 8.2275],
  BE: [50.5039, 4.4699],
  AT: [47.5162, 14.5501],
  NO: [60.472, 8.4689],
  DK: [56.2639, 9.5018],
  FI: [61.9241, 25.7482],
  NZ: [-40.9006, 174.886],
};

export type GeoPoint = {
  lat: number;
  lng: number;
  label: string;
};

export type GeoCollisionModel = {
  ip: GeoPoint;
  shipping: GeoPoint;
  precision: "coordinates" | "country_centroid";
  /** Great-circle distance for narrative (km). */
  straightLineKm: number;
};

export function normalizeIso2(input: unknown): string | null {
  if (typeof input !== "string") return null;
  const s = input.trim().toUpperCase();
  if (s.length === 2 && /^[A-Z]{2}$/.test(s)) return s;
  if (s === "USA") return "US";
  if (s === "UK" || s === "UNITED KINGDOM") return "GB";
  return null;
}

function pickNum(o: Record<string, unknown>, ...keys: string[]): number | null {
  for (const k of keys) {
    const v = o[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

export function haversineKm(a: Pick<GeoPoint, "lat" | "lng">, b: Pick<GeoPoint, "lat" | "lng">): number {
  const R = 6371;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const x =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(x)));
}

function parseGeoPoint(obj: unknown, fallbackLabel: string): GeoPoint | null {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return null;
  const o = obj as Record<string, unknown>;
  const lat = pickNum(o, "lat", "latitude");
  const lng = pickNum(o, "lng", "lon", "longitude");
  if (lat == null || lng == null) return null;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
  const label =
    typeof o.label === "string" && o.label.trim().length > 0 ? o.label.trim() : fallbackLabel;
  return { lat, lng, label };
}

function readGeoCollisionBlock(payload: Record<string, unknown>): GeoCollisionModel | null {
  const gc = payload.geo_collision;
  if (!gc || typeof gc !== "object" || Array.isArray(gc)) return null;
  const g = gc as Record<string, unknown>;
  const ip = parseGeoPoint(g.ip, "Session IP");
  const shipping = parseGeoPoint(
    g.shipping ?? g.ship_to ?? g.shipping_address,
    "Ship-to address",
  );
  if (!ip || !shipping) return null;
  return {
    ip,
    shipping,
    precision: "coordinates",
    straightLineKm: haversineKm(ip, shipping),
  };
}

function extractFromCountryCodes(payload: Record<string, unknown>): GeoCollisionModel | null {
  const ipCc =
    normalizeIso2(payload.geo_country) ??
    normalizeIso2(payload.ip_country) ??
    normalizeIso2((payload.metadata as Record<string, unknown> | undefined)?.geo_country);

  let shipCc =
    normalizeIso2(payload.shipping_country) ??
    normalizeIso2(payload.ship_country) ??
    normalizeIso2(payload.ship_to_country);

  const meta = payload.metadata;
  if (!shipCc && meta && typeof meta === "object" && !Array.isArray(meta)) {
    shipCc =
      normalizeIso2((meta as Record<string, unknown>).shipping_country) ??
      normalizeIso2((meta as Record<string, unknown>).ship_country);
  }

  if (!ipCc || !shipCc) return null;

  const ipCent = ISO2_CENTROID[ipCc];
  const shipCent = ISO2_CENTROID[shipCc];
  if (!ipCent || !shipCent) return null;

  if (ipCc === shipCc) return null;

  const ip: GeoPoint = { lat: ipCent[0], lng: ipCent[1], label: `IP region (${ipCc})` };
  const shipping: GeoPoint = {
    lat: shipCent[0],
    lng: shipCent[1],
    label: `Ship-to (${shipCc})`,
  };

  return {
    ip,
    shipping,
    precision: "country_centroid",
    straightLineKm: haversineKm(ip, shipping),
  };
}

/**
 * Extract IP vs ship-to locations from `evaluate_payload` (audit envelope).
 * Prefers structured `geo_collision`; falls back to ISO country centroids when coordinates absent.
 */
export function extractGeoCollisionModel(
  payload: Record<string, unknown> | null | undefined,
): GeoCollisionModel | null {
  if (!payload || typeof payload !== "object") return null;

  const block = readGeoCollisionBlock(payload);
  if (block) return block;

  return extractFromCountryCodes(payload);
}
