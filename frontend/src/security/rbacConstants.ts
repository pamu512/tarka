/** Well-known application roles referenced by route guards (must match IdP / backend JWT strings). */
export const TarkaRbacRole = {
  FraudAnalyst: "FraudAnalyst",
  RiskArchitect: "RiskArchitect",
  Admin: "admin",
  Analyst: "analyst",
  Viewer: "viewer",
  Service: "service",
} as const;

export type TarkaRbacRoleName = (typeof TarkaRbacRole)[keyof typeof TarkaRbacRole];
