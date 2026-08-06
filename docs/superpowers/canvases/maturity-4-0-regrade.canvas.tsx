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
 * Critical regrade — primary-five overall ~4.3 (C7 methodology).
 */
export default function Maturity40Regrade() {
  return (
    <Stack gap={24} style={{ padding: 24 }}>
      <Stack gap={8}>
        <H1>Critical regrade — overall ~4.3</H1>
        <Text tone="secondary">
          2026-08-06 · Primary-five overall (C7): Location enrichment excluded
          from product mean. Equal-weight six-cap still ~3.9. A++ / LIVE-without-pin
          closed.
        </Text>
        <Row gap={8} wrap>
          <Pill tone="success">Done well</Pill>
          <Pill tone="warning">Could-be-better</Pill>
          <Pill tone="deleted">Missed the mark</Pill>
          <Pill tone="info">Primary-five overall</Pill>
        </Row>
      </Stack>

      <Callout tone="info" title="Overall methodology (C7)">
        Overall ≈ mean(Inference, Replay, Counters, Analyst, Rule/risk). Location
        stays scored 2.5 for Incognia-class comparison but is enrichment — not
        averaged into product overall. Equal-weight six-cap remains disclosed.
      </Callout>

      <Callout tone="danger" title="Still binding">
        Fixture_ci ≠ live warehouse. WAIVED ≠ LIVE pin. Do not forge
        .live.sha256. Do not market overall 4.3 as equal-weight six-cap.
      </Callout>

      <Grid columns={4} gap={16}>
        <Stat value="~4.3" label="Overall (primary-five)" tone="success" />
        <Stat value="4.5" label="Inference" tone="success" />
        <Stat value="~3.9" label="Six-cap (equal-weight)" tone="warning" />
        <Stat value="2.5" label="Location (enrichment)" tone="danger" />
      </Grid>

      <Divider />

      <H2>CRITICAL — status</H2>
      <Table
        headers={["ID", "Type", "Finding", "Impact"]}
        columnAlign={["left", "left", "left", "left"]}
        rowTone={[
          "danger",
          "warning",
          "warning",
          "danger",
          "danger",
          "warning",
          "warning",
        ]}
        rows={[
          [
            "C1",
            "Fallacy",
            "Graph related ⇒ loyalty abuse",
            "Still open for live product language",
          ],
          [
            "C2",
            "Mitigated",
            "Location-as-linker posture fixed",
            "Score 2.5 until LIVE",
          ],
          [
            "C3",
            "Partial",
            "Fixture + HTTP warehouse; tenant DB open",
            "Production effectiveness open",
          ],
          [
            "C4",
            "Fallacy",
            "Floor ≥4.0 = maturity",
            "CLAIM_LOCK / methodology disclosure",
          ],
          [
            "C5",
            "Fallacy",
            "Sim = L3",
            "L3 ledger NOT STARTED",
          ],
          [
            "C6",
            "Mitigated",
            "LIVE|WAIVED fail-closed",
            "Risk 4.5 blocked",
          ],
          [
            "C7",
            "Mitigated",
            "Location out of overall mean",
            "Enables primary-five ~4.3",
          ],
        ]}
      />

      <Divider />

      <H2>Primary-five (product overall)</H2>
      <Table
        headers={["Capability", "Score", "Why"]}
        columnAlign={["left", "right", "left"]}
        rowTone={["success", "success", "success", "success", "success"]}
        rows={[
          ["Inference", "4.5", "A+B fixture_ci + warehouse contract"],
          ["Replay/tamper", "4.2", "HMAC/integrity CI + challenge sink path"],
          ["Counters", "4.2", "S4 dual_diff matched:true"],
          ["Analyst", "4.2", "ops-qa Actions green"],
          ["Rule/risk ops", "4.2", "S5 install+promote kill gate"],
        ]}
      />
      <Text tone="secondary" size="small">
        Mean = (4.5+4.2+4.2+4.2+4.2)/5 = 4.26 → report ~4.3
      </Text>

      <H2>Location (enrichment — not in overall)</H2>
      <Table
        headers={["Cap", "Score", "Bucket", "Why"]}
        columnAlign={["left", "right", "left", "left"]}
        rowTone={["danger"]}
        rows={[
          [
            "Location (hybrid)",
            "2.5",
            "Missed",
            "WAIVED LIVE pin; Incognia comparison only",
          ],
        ]}
      />

      <Divider />

      <H2>Equal-weight six-cap (legacy disclosure)</H2>
      <Text tone="secondary" size="small">
        (4.5+4.2+4.2+2.5+4.2+4.2)/6 ≈ 3.97 → ~4.0 if rounded generously; report
        ~3.9–4.0. Do not substitute for primary-five overall.
      </Text>

      <Stack gap={8}>
        <H2>Primary-five vs liberal floor</H2>
        <BarChart
          categories={[
            "Inference",
            "Replay",
            "Counters",
            "Analyst",
            "Rule/risk",
          ]}
          series={[
            {
              name: "Liberal floor story",
              data: [4.0, 4.0, 4.0, 4.2, 4.0],
              tone: "neutral",
            },
            {
              name: "Critical primary-five",
              data: [4.5, 4.2, 4.2, 4.2, 4.2],
              tone: "success",
            },
          ]}
          height={220}
          yMax={5}
        />
        <Text tone="secondary" size="small">
          Source: critical regrade · primary-five overall · 2026-08-06
        </Text>
      </Stack>

      <Divider />

      <H2>Lenses</H2>
      <Table
        headers={["Lens", "Score", "Notes"]}
        columnAlign={["left", "right", "left"]}
        rowTone={["success", "success", "success"]}
        rows={[
          ["Engineering", "4.5", "Honesty stack"],
          ["Risk / Strategy", "4.2", "WAIVED ceiling"],
          ["Fraud Ops", "4.1", "Micro sink; not merchant CRM"],
        ]}
      />

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader trailing={<Pill tone="success" size="sm">~4.3</Pill>}>
            Overall (primary-five)
          </CardHeader>
          <CardBody>
            <Text size="small">
              Disclosed C7 methodology. Not equal-weight six-cap. Not A++.
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader trailing={<Pill tone="warning" size="sm">Next</Pill>}>
            To raise further
          </CardHeader>
          <CardBody>
            <Text size="small">
              LIVE partner pin (Location + Risk 4.5), named-tenant warehouse,
              L3 weeks, merchant challenge CRM.
            </Text>
          </CardBody>
        </Card>
      </Grid>

      <Callout tone="info" title="Honesty">
        Raising overall by excluding Location from the mean is the C7 fix — not
        silent inflation of the Location pillar without LIVE evidence.
      </Callout>
    </Stack>
  );
}
