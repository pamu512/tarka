import {
  Callout,
  Card,
  CardBody,
  CardHeader,
  Divider,
  Grid,
  H1,
  H2,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  BarChart,
} from "cursor/canvas";

/**
 * Critical regrade — post S4/S5 (2026-08-06).
 * Done well / Could-be-better / Missed the mark.
 * Blindspots, fallacies, assumptions = CRITICAL.
 */
export default function Maturity40Regrade() {
  return (
    <Stack gap={24} style={{ padding: 24 }}>
      <Stack gap={8}>
        <H1>Critical regrade — Inference A+B claim</H1>
        <Text tone="secondary">
          2026-08-06 · maturity-4-0-local. Inference 4.5 on fixture_ci bar
          (ECE + S9). Aim bands are not current. A++ / product-wide 4.2 closed.
        </Text>
        <Row gap={8} wrap>
          <Pill tone="success">Done well</Pill>
          <Pill tone="warning">Could-be-better</Pill>
          <Pill tone="deleted">Missed the mark</Pill>
          <Pill tone="deleted">CRITICAL C1–C7</Pill>
        </Row>
      </Stack>

      <Callout tone="danger" title="CRITICAL — scoring fallacy (still binding)">
        Wiring + CI green ≠ loyalty-abuse effectiveness. In-repo floor ≥4.0 was
        walked back. Scores below are buckets, not aspirational bands.
      </Callout>

      <Grid columns={4} gap={16}>
        <Stat value="4.5" label="Engineering" tone="success" />
        <Stat value="4.2" label="Risk / Strategy" tone="success" />
        <Stat value="4.5" label="Inference (fixture_ci)" tone="success" />
        <Stat value="~3.9" label="Six-cap mean" tone="warning" />
      </Grid>

      <Divider />

      <H2>CRITICAL — blindspots, fallacies, assumptions</H2>
      <Table
        headers={["ID", "Type", "Finding", "Impact"]}
        columnAlign={["left", "left", "left", "left"]}
        rowTone={[
          "danger",
          "danger",
          "danger",
          "danger",
          "danger",
          "danger",
          "danger",
        ]}
        rows={[
          [
            "C1",
            "Fallacy",
            "Related accounts (graph) ⇒ loyalty abuse",
            "False + households; false − burn rings without economics",
          ],
          [
            "C2",
            "Assumption",
            "Signup / early location available to link accounts",
            "False under Apple/Google/web privacy — sparse enrichment only",
          ],
          [
            "C3",
            "Blindspot (partial)",
            "S9: engine+fixture CI landed; live warehouse feeds still required",
            "Contract proven; production loyalty effectiveness still open",
          ],
          [
            "C4",
            "Fallacy (hygiene)",
            "In-repo L1 / aim-band floor = product maturity",
            "CLAIM_LOCK.md — Wave6 4.2 withdrawn; A++ closed",
          ],
          [
            "C5",
            "Fallacy (path ready)",
            "Four-week sim ≠ L3 ops",
            "l3-ops-ledger NOT STARTED — sim never advances clock",
          ],
          [
            "C6",
            "Fallacy (mitigated)",
            "Fixture partner SHA ≠ live tenant",
            "2026-08-06 live BLOCKED (no creds); WAIVED status + attempt log",
          ],
          [
            "C7",
            "Blindspot",
            "Equal-weight Location pillar for loyalty-first thesis",
            "Wrong competitive emphasis vs graph + economics",
          ],
        ]}
      />

      <Divider />

      <H2>Done well</H2>
      <Table
        headers={["Area", "Evidence", "Critical score credit"]}
        columnAlign={["left", "left", "left"]}
        rowTone={[
          "success",
          "success",
          "success",
          "success",
          "success",
          "success",
          "success",
          "success",
        ]}
        rows={[
          [
            "Engineering honesty",
            "Lean mock audit + self-test; typed desk v1; stub AST; promote 409",
            "Engineering 4.5",
          ],
          [
            "Inference A+B (fixture_ci)",
            "ECE retrain gate + S9 loyalty feed smoke + combined claim gate",
            "Inference 4.5",
          ],
          [
            "Risk / Strategy honesty",
            "live.status LIVE|WAIVED + REQUIRE_LIVE_PARTNER_PROOF; promote kill CI; evidence index",
            "Risk/Strategy 4.2 (4.5 = LIVE .live.sha256)",
          ],
          [
            "Analyst desk gate",
            "ops-qa-desk e2e Actions green + Playwright artifact",
            "Analyst 4.2",
          ],
          [
            "Replay integrity (CI)",
            "HMAC / integrity tags / signature gates real in CI",
            "Replay 4.0 (not MitM product)",
          ],
          [
            "S4 counter matched:true",
            "PR CI Redis dual_diff; dry_run cannot greenwash",
            "Counters 4.0",
          ],
          [
            "S5 install kill gate",
            "/install shares promote metrics + evaluate_kill_criteria → 409",
            "Rule/risk 4.0",
          ],
          [
            "Claim discipline (late)",
            "Product-wide 4.2 closed; live loyalty warehouse still open",
            "Process credit — not a pillar score",
          ],
        ]}
      />

      <H2>Could have gone better</H2>
      <Table
        headers={["Area", "Gap", "Cost"]}
        columnAlign={["left", "left", "left"]}
        rowTone={["warning", "warning", "warning", "warning"]}
        rows={[
          [
            "Fraud Ops desk",
            "Challenge webhook often httpx-mocked; 4.4 needs live Micro sink",
            "Ops ~3.8 — triad real, live dispatch overstated",
          ],
          [
            "ECE / labels",
            "Track A CI fixture ECE green; live tenant chronological labels still absent",
            "Fixture L3 path only — not production weeks",
          ],
          [
            "Loyalty economics (Track B)",
            "S9 fixture CI green; live warehouse feeds + baselines still missing",
            "C3 partially closed (contract); live effectiveness open",
          ],
          [
            "Scoring process",
            "Repeated liberal floors (Wave6 4.2, then in-repo ≥4.0)",
            "Had to walk back twice — trust tax",
          ],
        ]}
      />

      <H2>Missed the mark</H2>
      <Table
        headers={["Area", "What we got wrong", "Critical score"]}
        columnAlign={["left", "left", "left"]}
        rowTone={["danger", "danger", "danger", "danger"]}
        rows={[
          [
            "Loyalty abuse effectiveness (live)",
            "Fixture S9 + engine real; live warehouse LTV/ledger/baselines still absent (C1, C3)",
            "Contract proven in CI — production effectiveness still open",
          ],
          [
            "Location as primary linker",
            "Scoreboard weight on hybrid location; loyalty rings don’t need signup GPS (C2, C7)",
            "Location 2.5 — enrichment only until live+useful",
          ],
          [
            "L2 live enrichment (data)",
            "OSS WAIVED — no named-tenant .live.sha256; L3 still playbook/sim (C5)",
            "Location 2.5; Risk 4.5 blocked until LIVE",
          ],
          [
            "Product-wide 4.x claims",
            "Brochure / aim-band language outran closed-loop proof (C4)",
            "Overall ~3.8 — not product-wide 4.2 / A++",
          ],
        ]}
      />

      <Divider />

      <H2>Six-capability critical scores (bucket-driven)</H2>
      <Table
        headers={["Capability", "Score", "Bucket", "Why"]}
        columnAlign={["left", "right", "left", "left"]}
        rowTone={[
          "success",
          "success",
          "success",
          "danger",
          "success",
          "success",
        ]}
        rows={[
          [
            "Inference",
            "4.5",
            "Done well",
            "A+B claim gate ok; bar=fixture_ci (not live warehouse L3)",
          ],
          [
            "Replay/tamper",
            "4.0",
            "Done well",
            "HMAC/integrity CI; ceiling MitM (disclose)",
          ],
          [
            "Counters",
            "4.0",
            "Done well",
            "S4: PR CI dual_diff + matched:true",
          ],
          [
            "Location (hybrid)",
            "2.5",
            "Missed",
            "No live pin; wrong weight for loyalty thesis (C2, C7)",
          ],
          [
            "Analyst",
            "4.2",
            "Done well",
            "ops-qa Actions green; not Sift queue OR",
          ],
          [
            "Rule/risk ops",
            "4.0",
            "Done well",
            "S5: install+promote share kill_criteria → 409",
          ],
        ]}
      />

      <Text tone="secondary" size="small">
        Mean = (4.5+4.0+4.0+2.5+4.2+4.0)/6 ≈ 3.87 → report ~3.9. Overall ~3.8.
        No product-wide 4.2. Inference 4.5 ≠ live loyalty product claim.
      </Text>

      <Stack gap={8}>
        <H2>Scores vs prior liberal / floor narratives</H2>
        <BarChart
          categories={[
            "Inference",
            "Replay",
            "Counters",
            "Location",
            "Analyst",
            "Rule/risk",
          ]}
          series={[
            {
              name: "Liberal / floor story",
              data: [4.0, 4.0, 4.0, 2.8, 4.2, 4.0],
              tone: "neutral",
            },
            {
              name: "Critical now (Inf 4.5 claim)",
              data: [4.5, 4.0, 4.0, 2.5, 4.2, 4.0],
              tone: "danger",
            },
          ]}
          height={240}
          yMax={5}
        />
        <Text tone="secondary" size="small">
          Source: critical bucket regrade · 2026-08-06 · Inference A+B fixture_ci
        </Text>
      </Stack>

      <Divider />

      <H2>End-user lenses</H2>
      <Table
        headers={["Lens", "Score", "Bucket", "Notes"]}
        columnAlign={["left", "right", "left", "left"]}
        rowTone={["success", "success", "warning"]}
        rows={[
          [
            "Engineering",
            "4.5",
            "Done well",
            "Honesty stack real; demo mockData residual (S8)",
          ],
          [
            "Risk / Strategy",
            "4.2",
            "Done well",
            "Honesty gate real; location data still Missed (2.5); 4.5 needs LIVE pin",
          ],
          [
            "Fraud Ops",
            "3.8",
            "Could-be-better",
            "Desk triad + kill gates; mocked webhook + C1/C3 block loyalty OR",
          ],
        ]}
      />

      <Divider />

      <H2>Loyalty abuse — prerequisite (C3 / S9)</H2>
      <Callout
        tone="danger"
        title="CRITICAL blindspot — model ineffective without upstream"
      >
        Engine + contract landed; tenant feeds still required: order velocity,
        churn, LTV, loyalty÷LTV, baselines. Graph = relatedness only. Guide:
        docs/docs/guides/loyalty-abuse-model-prerequisites.md
      </Callout>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader trailing={<Pill tone="deleted" size="sm">Closed</Pill>}>
            A++ / 4.5 claim
          </CardHeader>
          <CardBody>
            <Text size="small">
              Forbidden while any CRITICAL row (C1–C7) binds the claim surface.
              Loyalty-abuse product claim also requires S9 upstream feeds.
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="warning" size="sm">Next</Pill>}>
            Highest-leverage fixes
          </CardHeader>
          <CardBody>
            <Text size="small">
              1) Live warehouse feeds for production loyalty. 2) Reweight
              location / LIVE partner pin. 3) Ops live Micro sink. 4) Keep
              product-wide 4.2 closed until location moves.
            </Text>
          </CardBody>
        </Card>
      </Grid>

      <Callout tone="info" title="Honesty rule">
        Done well stays credited. Could-be-better keeps a haircut. Missed the
        mark and CRITICAL fallacies pull the mean down — even if CI is green.
      </Callout>
    </Stack>
  );
}
