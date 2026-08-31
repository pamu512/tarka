export type LiveRuleSlipRow = {
  rule_id: string;
  triggers: string[];
  hypothesis: string;
  parked_draft: string | null;
};

export function formatLiveRuleSlipLine(row: LiveRuleSlipRow): string {
  const triggers = row.triggers.join(", ");
  const tail = row.parked_draft ?? "ping only";
  return `${row.rule_id} · ${triggers} · ${row.hypothesis} · ${tail}`;
}
