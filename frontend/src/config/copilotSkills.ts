/** Preset skills for Investigation Copilot — shared by UI and `/skill` command. */

export type CopilotSkill = {
  id: string;
  label: string;
  prompt: string;
  instant?: boolean;
};

export type CopilotSkillGroup = {
  id: string;
  title: string;
  blurb?: string;
  skills: CopilotSkill[];
};

export const QUICK_INSTANT_SKILLS: CopilotSkill[] = [
  {
    id: "q-tldr",
    label: "⚡ Case TL;DR + top risks",
    instant: true,
    prompt:
      "Using this session's case context when present: give a tight TL;DR (5 bullets), top 3 fraud risks, and the single best next analyst action. Pull decision audit drivers if trace_id is available.",
  },
  {
    id: "q-rules",
    label: "⚡ Rule gaps from signals",
    instant: true,
    prompt:
      "From the current case/decision context, list 3 concrete rule-base or list changes (OPA-style intent, not code) that would catch similar fraud earlier. Rank by impact vs effort. Advisory only—do not assume changes are deployed.",
  },
  {
    id: "q-graph",
    label: "⚡ Graph + velocity hotspots",
    instant: true,
    prompt:
      "Describe how you would combine subgraph expansion with velocity/SDK signals for this entity to spot mule or ring behavior; list 4 specific signals to compare vs neighbors and what would justify escalation.",
  },
  {
    id: "q-triage",
    label: "⚡ Triage checklist",
    instant: true,
    prompt:
      "Output a numbered triage checklist for an analyst opening this case: evidence to collect, graph depth to run, list checks, when to escalate to L2 or SAR prep. Keep under 12 steps.",
  },
  {
    id: "q-handoff",
    label: "⚡ Shift handoff bullets",
    instant: true,
    prompt:
      "Draft concise shift handoff bullets (no PII): current hypothesis, what's verified, open questions, and what the next analyst should do first.",
  },
  {
    id: "q-digest",
    label: "⚡ Exec 10-bullet digest",
    instant: true,
    prompt:
      "Produce a template executive daily digest in exactly 10 bullets: volumes/decision mix, queue health, top entity themes, experiment status, incidents, and asks. Use placeholders where live metrics are unknown.",
  },
];

export const COPILOT_SKILL_GROUPS: CopilotSkillGroup[] = [
  {
    id: "rules-cases",
    title: "Cases & rule base",
    blurb: "Review existing work and suggest improvements to policies, lists, and thresholds—always advisory.",
    skills: [
      {
        id: "rc-cohort-rules",
        label: "Cohort rule review (open / high priority)",
        prompt:
          "Analyze patterns across open and high-priority cases from the last 7 days (velocity, shared devices, geo/SDK, repeat entities). Suggest concrete rule, list, or threshold changes ranked by estimated impact vs implementation effort. Note dependencies on graph or batch exports if needed. Do not state that anything was applied.",
      },
      {
        id: "rc-drivers",
        label: "Audit driver drift vs last month",
        prompt:
          "Compare decision audit inference drivers and rule hits for the current case cohort vs a typical prior window. Which rule families look noisy (too many false positives) vs under-firing? Suggest specific threshold, tag, or segmentation tweaks and what to measure after each change.",
      },
      {
        id: "rc-velocity-sdk",
        label: "Velocity + automation cluster playbook",
        prompt:
          "Focus on velocity spikes combined with SDK/automation or VPN signals in recent cases. Propose 2–3 guardrail patterns (rules + monitoring), expected false-positive tradeoffs, and KPIs to watch for 14 days post-change.",
      },
      {
        id: "rc-replay",
        label: "A/B replay plan for two rule variants",
        prompt:
          "Outline how to run a replay or shadow comparison between rule variant A and B on labeled historical cases/disputes: segments to hold constant, success metrics (review rate, catch rate, $ exposure), minimum sample size guidance, and when results are conclusive. Reference tenant-safe synthetic data if live exports unavailable.",
      },
    ],
  },
  {
    id: "batch-data",
    title: "Batch data & deep analysis",
    blurb: "Structured thinking for exports, backfills, and cohort studies.",
    skills: [
      {
        id: "bd-plan",
        label: "Batch analysis plan + hypotheses",
        prompt:
          "I am preparing a batch export of decisions and/or cases for this tenant. Propose: (1) segmentation dimensions (score bands, geo, channel, entity age), (2) 5 testable fraud hypotheses, (3) tables/charts an analyst should build first, (4) data quality checks before trusting conclusions, (5) suggested next steps after first pass.",
      },
      {
        id: "bd-drift",
        label: "Degradation vs seasonality",
        prompt:
          "Explain how to distinguish model or rule degradation from normal seasonality or marketing campaigns in batch decision data. Suggest control cohorts, rolling windows, alert thresholds (advisory), and when to trigger a full model or rules review.",
      },
      {
        id: "bd-fp-labels",
        label: "False-positive review cohort design",
        prompt:
          "Design a cohort definition for likely false-positive manual reviews (using case status, dispute outcomes, analyst labels where available). List fields to pull from cases + decision audits for a training or calibration set, and ethical/privacy cautions.",
      },
      {
        id: "bd-sar-prep",
        label: "Batch → SAR narrative outline",
        prompt:
          "From a hypothetical batch of linked high-risk cases, produce an outline for SAR-style narrative sections (facts, timeline, suspects, amounts, law-enforcement value). Mark every item as requiring human verification—template only.",
      },
    ],
  },
  {
    id: "experiments",
    title: "A/B tests, shadow & simulation",
    blurb: "Read out experiments and decide what to ship—guardrails included.",
    skills: [
      {
        id: "ex-checklist",
        label: "A/B readout checklist",
        prompt:
          "Give a structured checklist for interpreting an A/B or shadow test between two fraud policies: primary metrics (review/deny/FP proxy), segment stability, duration vs power, ethical review, and go/no-go criteria before promoting the winner.",
      },
      {
        id: "ex-winner",
        label: "Recommend winner + rollback",
        prompt:
          "Assume treatment A emphasizes velocity and B emphasizes device reputation for the same traffic slice. Compare expected outcomes for high-value payments: which wins on loss avoidance vs customer friction, what 7-day guardrails to run after cutover, and explicit rollback triggers if review volume explodes.",
      },
      {
        id: "ex-shadow",
        label: "Shadow mode monitoring plan",
        prompt:
          "Draft a 2-week monitoring plan for a rule pack running in shadow only: metrics to diff vs production, dashboards, alert thresholds, and a decision meeting agenda to promote or discard.",
      },
    ],
  },
  {
    id: "reporting",
    title: "Reports & monitoring periods",
    blurb: "Recurring operational and executive views—edit dates in the composer after insert.",
    skills: [
      {
        id: "rp-weekly",
        label: "Weekly fraud-ops monitoring report",
        prompt:
          "Generate a structured weekly monitoring report for fraud operations (tenant scope: current context). Sections: (1) volume & decision mix, (2) queue SLA & aging, (3) top entities & communities, (4) rule hit leaders & anomalies, (5) graph/ring callouts, (6) experiments in flight, (7) open actions. Replace [START_DATE]–[END_DATE] with my range after I edit.",
      },
      {
        id: "rp-kpi",
        label: "KPI dashboard spec",
        prompt:
          "Specify a minimal KPI dashboard for ongoing monitoring: 8–10 tiles with definition, data source (cases, decisions, graph, analytics), refresh cadence, and red/yellow thresholds. Include one tile for copilot/rule change audit volume if applicable.",
      },
      {
        id: "rp-incident",
        label: "Post-incident summary template",
        prompt:
          "Create a post-incident summary template for a fraud spike: timeline, blast radius, root cause hypotheses, mitigations deployed, residual risk, and follow-up tasks. Leave bracketed placeholders for dates and IDs.",
      },
    ],
  },
  {
    id: "workflow",
    title: "Analyst workflow shortcuts",
    blurb: "Less typing for common operational tasks.",
    skills: [
      {
        id: "wf-dispute",
        label: "Dispute response outline",
        prompt:
          "Given chargeback or dispute context for this case, outline evidence to gather, narrative angles (fraud vs friendly fraud), and a response checklist for the disputes team. Advisory only.",
      },
      {
        id: "wf-integrations",
        label: "Integration health questions",
        instant: true,
        prompt:
          "List the top 8 questions an analyst should ask when OSINT or third-party enrichment looks stale or contradictory for a case (API health, cache, false negatives). Keep answers as a checklist.",
      },
      {
        id: "wf-compliance",
        label: "Compliance evidence request list",
        prompt:
          "Produce a bullet list of artifacts an auditor might request for a sample of denied/reviewed transactions (decision audit, rule version, model lineage placeholder, access logs). No legal advice—operational checklist only.",
      },
      {
        id: "wf-oncall",
        label: "Oncall runbook snippet",
        instant: true,
        prompt:
          "Generate a compact oncall runbook snippet: symptom → checks (cases, decisions, graph, integrations) → escalate path. Fraud platform context.",
      },
    ],
  },
];

export function getAllCopilotSkills(): CopilotSkill[] {
  return [...QUICK_INSTANT_SKILLS, ...COPILOT_SKILL_GROUPS.flatMap((g) => g.skills)];
}

/** `/skill` or `/skills` with optional subquery. */
export function parseSkillCommand(raw: string): { isSkillCommand: boolean; rest: string } {
  const t = raw.trim();
  const m = t.match(/^\/skills?(?:\s+(.*))?$/i);
  if (!m) return { isSkillCommand: false, rest: "" };
  return { isSkillCommand: true, rest: (m[1] ?? "").trim() };
}

export function findCopilotSkillByQuery(query: string): CopilotSkill | undefined {
  const q = query.trim().toLowerCase();
  if (!q) return undefined;
  const all = getAllCopilotSkills();
  const byId = all.find((s) => s.id.toLowerCase() === q);
  if (byId) return byId;
  const slug = q.replace(/\s+/g, "-");
  const bySlug = all.find((s) => s.id.toLowerCase() === slug);
  if (bySlug) return bySlug;
  return all.find((s) => s.label.toLowerCase().includes(q) || q.includes(s.id.toLowerCase()));
}

export function buildSkillCommandHelp(): string {
  const lines: string[] = [
    "**Copilot skills** — preset playbooks (this chat only; not sent to the model training).",
    "",
    "**Commands**",
    "• `/skill` or `/skill list` — show this catalog.",
    "• `/skill <id>` — show one skill’s full prompt (e.g. `/skill q-tldr`, `/skill rc-cohort-rules`).",
    "• `/skill <words>` — fuzzy match on label (e.g. `/skill weekly report`).",
    "",
    "**Quick run (instant ⚡)**",
    ...QUICK_INSTANT_SKILLS.map((s) => `  • \`${s.id}\` — ${s.label}`),
    "",
  ];
  for (const g of COPILOT_SKILL_GROUPS) {
    lines.push(`**${g.title}**`);
    if (g.blurb) lines.push(`  (${g.blurb})`);
    for (const s of g.skills) {
      const tag = s.instant ? " ⚡" : "";
      lines.push(`  • \`${s.id}\`${tag} — ${s.label.replace(/^⚡\s*/, "")}`);
    }
    lines.push("");
  }
  lines.push(
    "**Custom skills**",
    "If you repeat the same prompt often, save it as a named custom skill (see the hint after duplicate sends). Product: Settings → Copilot → Custom skills (planned) or your team runbook.",
  );
  return lines.join("\n");
}

export function formatSkillDetail(skill: CopilotSkill): string {
  const instantNote = skill.instant
    ? "**⚡ Instant skill** — you can run the same text from the preset buttons, or paste below and Send.\n\n"
    : "**Composer skill** — paste into the box, edit placeholders (dates, tenant), then Send.\n\n";
  return [
    `**${skill.label}**  (\`${skill.id}\`)`,
    "",
    instantNote,
    "**Prompt**",
    "```",
    skill.prompt,
    "```",
  ].join("\n");
}

/** Normalize user text to detect repeated tasks in-session. */
export function normalizePromptForRepeatDetection(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .slice(0, 400);
}

export function buildRepeatSkillSuggestionPrompt(lastUserMessage: string): string {
  const clip =
    lastUserMessage.length > 600 ? `${lastUserMessage.slice(0, 600)}…` : lastUserMessage;
  return [
    "**Repeat task detected** — you’ve sent a very similar message more than once in this chat.",
    "",
    "**Save it as a custom skill** so the team gets one-tap or short-alias access:",
    "1. **Name** — short verb + object (e.g. `Weekly queue risk scrub`).",
    "2. **Prompt** — copy the text you reuse (template below). Add `[PLACEHOLDERS]` for dates, entity, or tenant.",
    "3. **Where to store** — until in-app custom skills ship: team wiki / runbook, or ask an admin to add a **preset** next to the built-ins.",
    "4. **Instant vs edit** — if the prompt is always the same, mark it *instant*; if analysts must edit dates/IDs, keep it *composer-first*.",
    "",
    "**Tip** — Type `/skill` anytime to list every preset **id** and label.",
    "",
    "**Your last message (copy as skill body)**",
    "```",
    clip,
    "```",
  ].join("\n");
}
