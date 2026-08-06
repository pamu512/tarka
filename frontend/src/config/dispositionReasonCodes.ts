/** Case disposition reason codes → calibration ground truth (bridge B2). */

export const DISPOSITION_REASON_CODES = [
  { code: "CONFIRMED_FRAUD", label: "Confirmed fraud", yLabel: "FRAUD" },
  { code: "ACCOUNT_TAKEOVER", label: "Account takeover", yLabel: "FRAUD" },
  { code: "FRIENDLY_FRAUD", label: "Friendly fraud", yLabel: "FRAUD" },
  { code: "SAR_FILED", label: "SAR filed", yLabel: "FRAUD" },
  { code: "FALSE_POSITIVE", label: "False positive", yLabel: "LEGITIMATE" },
  { code: "CUSTOMER_CLEARED", label: "Customer cleared", yLabel: "LEGITIMATE" },
  { code: "INSUFFICIENT_EVIDENCE", label: "Insufficient evidence", yLabel: "LEGITIMATE" },
] as const;

export type DispositionReasonCode = (typeof DISPOSITION_REASON_CODES)[number]["code"];

const TERMINAL = new Set(["resolved", "closed", "resolved_fraud", "resolved_legit", "sar_filed"]);

export function isTerminalCaseStatus(status: string | null | undefined): boolean {
  return TERMINAL.has(String(status || "").toLowerCase());
}

export function yLabelForReasonCode(code: string): "FRAUD" | "LEGITIMATE" | null {
  const row = DISPOSITION_REASON_CODES.find((r) => r.code === code);
  return row ? row.yLabel : null;
}

export function isDispositionReasonCode(code: string): code is DispositionReasonCode {
  return DISPOSITION_REASON_CODES.some((r) => r.code === code);
}
