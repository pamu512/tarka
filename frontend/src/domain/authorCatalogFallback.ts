import { CATALOG_HOPS, type AuthorCatalog } from "./authorCatalog";

const FALLBACK_REDIS: AuthorCatalog["redis"] = [
  { name: "event_count_5m", kind: "event_count", window: "5m", window_seconds: 300 },
  { name: "event_count_1h", kind: "event_count", window: "1h", window_seconds: 3600 },
  { name: "event_count_24h", kind: "event_count", window: "24h", window_seconds: 86400 },
  { name: "event_count_7d", kind: "event_count", window: "7d", window_seconds: 604800 },
  { name: "sum_amount_1h", kind: "sum", window: "1h", window_seconds: 3600, field: "amount" },
  { name: "avg_amount_1h", kind: "avg", window: "1h", window_seconds: 3600, field: "amount" },
  { name: "sum_amount_24h", kind: "sum", window: "24h", window_seconds: 86400, field: "amount" },
  { name: "avg_amount_24h", kind: "avg", window: "24h", window_seconds: 86400, field: "amount" },
  { name: "distinct_ip_address_24h", kind: "distinct", window: "24h", window_seconds: 86400, field: "ip_address" },
  { name: "distinct_device_id_24h", kind: "distinct", window: "24h", window_seconds: 86400, field: "device_id" },
  { name: "distinct_session_id_24h", kind: "distinct", window: "24h", window_seconds: 86400, field: "session_id" },
];

const FALLBACK_PAYLOAD: AuthorCatalog["payload"] = [
  { name: "amount" },
  { name: "currency" },
  { name: "device_type" },
  { name: "is_bot" },
  { name: "is_emulator" },
  { name: "is_rooted" },
  { name: "is_vpn" },
  { name: "session_duration" },
  { name: "country" },
  { name: "ip_is_proxy" },
  { name: "distinct_countries_7d" },
  { name: "email_domain" },
];

export function fallbackAuthorCatalog(): AuthorCatalog {
  return {
    redis: FALLBACK_REDIS,
    growth: [],
    hops: CATALOG_HOPS.map((etype) => ({ etype })),
    payload: FALLBACK_PAYLOAD,
  };
}
