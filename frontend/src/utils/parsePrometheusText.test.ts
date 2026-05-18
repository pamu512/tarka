import { describe, expect, it } from "vitest";
import { parsePrometheusText } from "./parsePrometheusText";

describe("parsePrometheusText", () => {
  it("sums http_requests_total and picks notable counters", () => {
    const text = `
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{service="x",method="GET",path="/v1/health",status="200",tenant_query="absent"} 10
http_requests_total{service="x",method="POST",path="/v1/cases",status="201",tenant_query="present"} 2
# TYPE tarka_load_shedding_active_total counter
tarka_load_shedding_active_total{service="x"} 3
events_ingested_total{service="ingest"} 99
`;
    const d = parsePrometheusText(text);
    expect(d.httpRequestsTotal).toBe(12);
    expect(d.notableCounters.some((c) => c.name === "tarka_load_shedding_active_total")).toBe(true);
    expect(d.notableCounters.some((c) => c.name === "events_ingested_total")).toBe(true);
  });
});
