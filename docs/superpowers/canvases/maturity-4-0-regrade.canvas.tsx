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
 * Critical regrade — Done well / Could-be-better / Missed the mark.
 * Blindspots, logic fallacies, and bad assumptions marked CRITICAL.
 */
export default function Maturity40Regrade() {
  return (
    <Stack gap={24} style={{ padding: 24 }}>
      <Stack gap={8}>
        <H1>Critical regrade — three buckets</H1>
        <Text tone="secondary">
          2026-08-06 · maturity-4-0-local. Scores from evidence buckets, not aim
          bands. Blindspots / fallacies / assumptions = CRITICAL. A++ closed.
        </Text>
        <Row gap={8} wrap>
          <Pill tone="success">Done well</Pill>
          <Pill tone="warning">Could-be-better</Pill>
          <Pill tone="danger">Missed the mark</Pill>
          <Pill tone="danger">CRITICAL fallacies</Pill>
        </Row>
      </Stack>

      <Callout tone="danger" title="CRITICAL — scoring fallacy (walked back)">
        Treating “in-repo floor ≥4.0” as product effectiveness was itself a
        logic error. Wiring + one CI green ≠ an effective loyalty-abuse or
        risk model. Scores below reflect buckets, not aspirational floors.
      </Callout>

      <Grid columns={4} gap={16}>
        <Stat value="4.5" label="Engineering" tone="success" />
        <Stat value="4.2" label="Risk / Strategy" tone="success" />
        <Stat value="~3.6" label="Overall (critical)" tone="warning" />
        <Stat value="~3.6" label="Six-cap mean" tone="warning" />
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
            "False positive households; false negative burn rings without economics",
          ],
          [
            "C2",
            "Assumption",
            "Signup / early location available to link accounts",
            "False under Apple/Google/web privacy — location is sparse enrichment",
          ],
          [
            "C3",
            "Blindspot",
            "S9: engine+contract landed; tenant feeds still required",
            "Loyalty-abuse model ineffective until upstream baselines exist",
          ],
          [
            "C4",
            "Fallacy",
            "In-repo L1 / aim-band floor = product maturity score",
            "Inflates Inference/Counters/Rule when closed-loop proof missing",
          ],
          [
            "C5",
            "Fallacy",
            "Four-week sim / playbook = L3 ops evidence",
            "Banner says NOT PRODUCTION L3 — still easy to over-claim",
          ],
          [
            "C6",
            "Fallacy (mitigated)",
            "Fixture partner SHA = live tenant enrichment",
            "Closed as process: live.status LIVE|WAIVED fail-closed in CI — location still 2.5 until LIVE pin (aim Risk 4.5)",
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
        ]}
        rows={[
          [
            "Engineering honesty",
            "Lean mock audit + self-test; typed desk v1; stub AST; promote 409",
            "Engineering 4.5",
          ],
          [
            "Risk / Strategy honesty",
            "live.status LIVE|WAIVED + REQUIRE_LIVE_PARTNER_PROOF; kill_criteria promote CI; evidence index",
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
            "Counter vanity kill + S4",
            "PR CI dual_diff Redis; matched:true required (dry_run not proof)",
            "Counters → 4.0 Done well",
          ],
          [
            "S5 install kill gate",
            "/install same metrics body + evaluate_kill_criteria → 409",
            "Rule/risk → 4.0 Done well",
          ],
          [
            "Claim discipline (late)",
            "L1∧L2∧L3 lock; S9 loyalty prereq doc; Wave6 4.2 walked back",
            "Process credit — not a pillar score",
          ],
        ]}
      />

      <H2>Could have gone better</H2>
      <Table
        headers={["Area", "Gap", "Cost"]}
        columnAlign={["left", "left", "left"]}
        rowTone={["warning", "warning", "warning"]}
        rows={[
          [
            "Fraud Ops desk",
            "Challenge webhook often httpx-mocked; 4.4 needs live Micro sink",
            "Ops 4.3 overstates live dispatch",
          ],
          [
            "ECE / labels",
            "calibration_fit + retrain CLI unused on real chronological labels",
            "Inference stretch fake without S3",
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
            "Loyalty abuse effectiveness",
            "Graph + generic velocity sold the story; no cluster LTV / loyalty÷LTV / churn economics (C1, C3)",
            "Inference loyalty vertical: fail — platform plumbing ≠ model",
          ],
          [
            "Location as primary linker",
            "Invested scoreboard weight in hybrid location; loyalty rings don’t need signup GPS (C2, C7)",
            "Location 2.5 — enrichment only until live+useful",
          ],
          [
            "L2 live enrichment (data)",
            "OSS WAIVED — no named-tenant .live.sha256 yet; L3 still playbook/sim (C5)",
            "Location 2.5; Risk strategy 4.2; Risk 4.5 blocked until LIVE",
          ],
          [
            "Product-wide 4.x claims",
            "Brochure / aim-band language outran closed-loop proof (C4)",
            "Overall ~3.5 — not 4.0 / 4.2 / A++",
          ],
        ]}
      />

      <Divider />

      <H2>Six-capability critical scores (bucket-driven)</H2>
      <Table
        headers={["Capability", "Score", "Bucket", "Why"]}
        columnAlign={["left", "right", "left", "left"]}
        rowTone={[
          "danger",
          "success",
          "success",
          "danger",
          "success",
          "success",
        ]}
        rows={[
          [
            "Inference",
            "3.4",
            "Missed",
            "Labels/ECE plumbing real; loyalty economics absent (C3); live ECE unused",
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
            "S4: PR CI dual_diff + matched:true (not dry_run vanity)",
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
        Mean = (3.4+4.0+4.0+2.5+4.2+4.0)/6 ≈ 3.68 → report ~3.7. Lenses:
        Engineering 4.5 · Risk/Strategy 4.2 · Fraud Ops ~3.8 (desk triad haircut for
        mocked webhook + no loyalty economics). Overall ~3.6. No product-wide 4.2.
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
              name: "Critical now (buckets)",
              data: [3.4, 4.0, 4.0, 2.5, 4.2, 4.0],
              tone: "danger",
            },
          ]}
          height={240}
          yMax={5}
        />
      </Stack>

      <Divider />

      <H2>End-user lenses</H2>
      <Table
        headers={["Lens", "Score", "Bucket", "Notes"]}
        columnAlign={["left", "right", "left", "left"]}
        rowTone={["success", "danger", "warning"]}
        rows={[
          [
            "Engineering",
            "4.5",
            "Done well",
            "Honesty stack real; demo mockData residual (S8)",
          ],
          [
            "Risk / Strategy",
            "3.2",
            "Missed",
            "C2/C6/C7 — location theater + wrong loyalty linker thesis",
          ],
          [
            "Fraud Ops",
            "3.8",
            "Could-be-better",
            "Desk triad / promote gates; C1/C3 block loyalty effectiveness",
          ],
        ]}
      />

      <Divider />

      <H2>Loyalty abuse — prerequisite (C3 / S9)</H2>
      <Callout tone="danger" title="CRITICAL blindspot — model ineffective without upstream">
        Engine + contract landed (`loyalty_economics.py`, multi-gate schema); tenant
        feeds still required: order velocity, churn, LTV, loyalty÷LTV, baselines.
        Graph = relatedness only. Guide:
        docs/docs/guides/loyalty-abuse-model-prerequisites.md
      </Callout>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader trailing={<Pill tone="danger" size="sm">Closed</Pill>}>
            A++ / 4.5 claim
          </CardHeader>
          <CardBody>
            <Text size="small">
              Forbidden while any CRITICAL row (C1–C7) is open for the claim
              surface. Loyalty-abuse product claim additionally requires S9
              upstream feeds.
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="warning" size="sm">Next</Pill>}>
            Highest-leverage fixes
          </CardHeader>
          <CardBody>
            <Text size="small">
              1) S9 upstream + cluster economics model. 2) Reweight location as
              enrichment not linker. 3) Live L2 partner only if it feeds real
              decisions. 4) Stop scoring aim bands as current.
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
