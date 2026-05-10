export type AuditRecentStatus =
  | "BLOCK"
  | "FLAG"
  | "SHADOW_REVIEW"
  | "ALLOW";

export type AuditRecentItem = {
  timestamp: string;
  transaction_id: string;
  amount_cents: number;
  status: AuditRecentStatus;
};

export type AuditRecentResponse = {
  items: AuditRecentItem[];
};
