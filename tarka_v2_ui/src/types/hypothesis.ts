/**
 * DuckDB Scout / shadow hypothesis payloads (Prompts 194–196) for analyst UI.
 */

export type HypothesisFingerprintKind = "canvas_hash" | "webgl_vendor";

export type HypothesisReport = {
  report_id: string;
  strategy?: "coordinated_burst";
  fingerprint_kind: HypothesisFingerprintKind;
  fingerprint_value: string;
  distinct_account_count: number;
  narrative?: string;
  saarthi_narrative?: string | null;
  confidence?: number;
  analyst_suggestion_allowed?: boolean;
  backtest_false_positive_rate?: number | null;
  backtest_lookback_days?: number | null;
  suggested_rule?: Record<string, unknown> | null;
  backtest_validation?: Record<string, unknown> | null;
};

export type ScoutCoordinatedBurstPayload = {
  hypothesis_reports?: HypothesisReport[];
  hypothesis_reports_blocked?: HypothesisReport[];
  scout_summary?: string;
  bursts_found?: number;
};
