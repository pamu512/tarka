/** Core analyst flows: focusable landmark selectors for keyboard QA. */
export const CORE_FLOW_LANDMARKS = [
  { route: "/cases", main: "main", heading: "h1" },
  { route: "/rules", main: "main", heading: "h1" },
  { route: "/investigation", main: "main", heading: "h1" },
] as const;

export function assertLandmarkContract(doc: {
  querySelector: (sel: string) => unknown;
}): string[] {
  const missing: string[] = [];
  if (!doc.querySelector("main")) missing.push("main");
  if (!doc.querySelector("h1, [role='heading']")) missing.push("heading");
  return missing;
}
