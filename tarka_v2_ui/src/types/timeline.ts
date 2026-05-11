export type TimelineEvent = {
  audit_log_id: number;
  transaction_id: string;
  timestamp: string;
  investigation_case_number: string;
  case_outcome: string;
  amount?: number | null;
  is_fraud?: boolean | null;
  device_id?: string | null;
  ip_address?: string | null;
  shadow_case_id: string;
  highlight?: "cross_case" | null;
  matched_via: "entity_scope" | "device_id" | "ip_address";
};

export type TimelineResponse = {
  entity_id: string;
  anchor_case_number?: string | null;
  anchor_timestamp?: string | null;
  events: TimelineEvent[];
  alerts: string[];
  warning?: string;
};
