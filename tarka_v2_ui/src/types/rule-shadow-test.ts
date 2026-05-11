export type RuleShadowTestResponse = {
  sample_size: number;
  matched_count: number;
  match_rate: number;
  would_block_pct: number;
  would_flag_count: number;
  summary_line: string;
  warning: string | null;
};
