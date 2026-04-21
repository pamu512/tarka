import { useEffect, useState, type KeyboardEvent } from "react";
import {
  rules as rulesApi,
  simulation,
  ml,
  syncRuleGovernanceSecret,
  type RulePack,
  type RuleDetail,
  type DecisionRequest,
  type DecisionResponse,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";

// ── Constants ────────────────────────────────────────────────────────

/** N1: expanded no-code field catalog (datalist + picker). */
const FIELD_CATALOG: { category: string; fields: string[] }[] = [
  {
    category: "Payments & velocity",
    fields: [
      "amount",
      "currency",
      "transaction_count_24h",
      "failed_attempts_24h",
      "hour_of_day",
      "account_age_days",
    ],
  },
  {
    category: "Device & automation",
    fields: [
      "device_type",
      "is_bot",
      "is_emulator",
      "is_rooted",
      "is_vpn",
      "session_duration",
    ],
  },
  {
    category: "Network & geo",
    fields: ["country", "ip_is_proxy", "distinct_countries_7d", "email_domain"],
  },
];

const COMMON_FIELDS: string[] = Array.from(
  new Set(FIELD_CATALOG.flatMap((c) => c.fields)),
);

const OPERATORS: { value: string; label: string }[] = [
  { value: "eq", label: "= equals" },
  { value: "gte", label: "≥ greater or equal" },
  { value: "lte", label: "≤ less or equal" },
  { value: "gt", label: "> greater than" },
  { value: "lt", label: "< less than" },
  { value: "in", label: "in (list)" },
  { value: "contains", label: "contains" },
  { value: "is_true", label: "is true" },
  { value: "is_false", label: "is false" },
];

const BOOLEAN_OPS = new Set(["is_true", "is_false"]);

interface RuleTemplate {
  name: string;
  description: string;
  rule: Omit<RuleDetail, "id">;
}

const RULE_TEMPLATES: RuleTemplate[] = [
  {
    name: "High Amount",
    description: "Flag transactions over $5,000",
    rule: {
      description: "High amount transaction",
      score_delta: 15,
      tags: ["high_amount"],
      when: [{ field: "amount", op: "gte", value: 5000 }],
      enabled: true,
    },
  },
  {
    name: "VPN Detected",
    description: "User is behind a VPN",
    rule: {
      description: "VPN detected",
      score_delta: 10,
      tags: ["vpn"],
      when: [{ field: "is_vpn", op: "is_true", value: true }],
      enabled: true,
    },
  },
  {
    name: "Emulator",
    description: "Device is an emulator",
    rule: {
      description: "Emulator detected",
      score_delta: 20,
      tags: ["emulator"],
      when: [{ field: "is_emulator", op: "is_true", value: true }],
      enabled: true,
    },
  },
  {
    name: "New Account + High Amount",
    description: "New account with large transaction",
    rule: {
      description: "New account with high amount",
      score_delta: 25,
      tags: ["new_account", "high_amount"],
      when: [
        { field: "account_age_days", op: "lte", value: 7 },
        { field: "amount", op: "gte", value: 1000 },
      ],
      enabled: true,
    },
  },
  {
    name: "Velocity Spike",
    description: "High transaction velocity in 24h",
    rule: {
      description: "Velocity spike detected",
      score_delta: 15,
      tags: ["velocity"],
      when: [{ field: "transaction_count_24h", op: "gte", value: 20 }],
      enabled: true,
    },
  },
  {
    name: "Bot Detected",
    description: "Automated bot behavior",
    rule: {
      description: "Bot behavior detected",
      score_delta: 30,
      tags: ["bot"],
      when: [{ field: "is_bot", op: "is_true", value: true }],
      enabled: true,
    },
  },
  {
    name: "Night Transaction",
    description: "Transaction during late night hours",
    rule: {
      description: "Night-time transaction",
      score_delta: 8,
      tags: ["night_txn"],
      when: [{ field: "hour_of_day", op: "lte", value: 4 }],
      enabled: true,
    },
  },
  {
    name: "Multi-Country",
    description: "Multiple countries in 7 days",
    rule: {
      description: "Multi-country activity",
      score_delta: 12,
      tags: ["multi_geo"],
      when: [{ field: "distinct_countries_7d", op: "gte", value: 3 }],
      enabled: true,
    },
  },
];

const DEFAULT_PAYLOAD = JSON.stringify(
  {
    event_type: "payment",
    entity_id: "user-123",
    tenant_id: "tenant-1",
    amount: 5000,
    currency: "USD",
    ip_address: "1.2.3.4",
  },
  null,
  2,
);
const VERTICAL_HISTORY_KEY = "tarka_vertical_benchmark_history";

let _ctr = 0;
function uid(): string {
  _ctr++;
  return `rule_${Date.now()}_${_ctr}`;
}

function parseValue(raw: string): unknown {
  if (raw === "") return "";
  const n = Number(raw);
  if (!isNaN(n) && raw.trim() !== "") return n;
  if (raw === "true") return true;
  if (raw === "false") return false;
  return raw;
}

function packFile(p: RulePack): string {
  return p._file ?? ((p as unknown as Record<string, unknown>).file as string | undefined) ?? p.name;
}

function normalizeRulePack(raw: RulePack, idx: number): RulePack {
  const rec = raw as unknown as Record<string, unknown>;
  const file =
    typeof raw._file === "string" && raw._file.trim()
      ? raw._file
      : typeof rec.file === "string" && rec.file.trim()
        ? rec.file
        : `pack_${idx + 1}.json`;
  const name =
    typeof raw.name === "string" && raw.name.trim()
      ? raw.name
      : file.replace(/\.json$/i, "");
  return {
    _file: file,
    name,
    version: typeof raw.version === "number" ? raw.version : 1,
    rules: Array.isArray(raw.rules) ? raw.rules : [],
    tag_rules: Array.isArray(raw.tag_rules) ? raw.tag_rules : [],
  };
}

// ── Main Component ───────────────────────────────────────────────────

export default function Rules() {
  const [packs, setPacks] = useState<RulePack[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [editingPack, setEditingPack] = useState<RulePack | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newPackName, setNewPackName] = useState("");
  const [creating, setCreating] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [simPayload, setSimPayload] = useState(DEFAULT_PAYLOAD);
  const [simResult, setSimResult] = useState<DecisionResponse | null>(null);
  const [simError, setSimError] = useState<string | null>(null);
  const [simulating, setSimulating] = useState(false);

  const [showTemplates, setShowTemplates] = useState(false);
  const [tagInputs, setTagInputs] = useState<Record<number, string>>({});
  const [toast, setToast] = useState<string | null>(null);
  const [verticalCatalog, setVerticalCatalog] = useState<Record<string, { name: string; rules: number; version: number }>>({});
  const [verticalHistory, setVerticalHistory] = useState<Array<{
    ts: string;
    scenario: string;
    vertical: string;
    baseline_f1: number;
    vertical_f1: number;
    delta_f1: number;
  }>>([]);
  const [installingVertical, setInstallingVertical] = useState<string | null>(null);
  const [benchmarkingVertical, setBenchmarkingVertical] = useState<string | null>(null);
  const [benchmarkScenario, setBenchmarkScenario] = useState<string>("baseline");
  const [lineageModelName, setLineageModelName] = useState("fraud");
  const [lineageVersion, setLineageVersion] = useState<number>(1);
  const [lineageHash, setLineageHash] = useState<string>("");
  const [lineageBusy, setLineageBusy] = useState(false);
  const [ruleActor, setRuleActor] = useState(() =>
    typeof localStorage !== "undefined" ? localStorage.getItem("tarka.rule_actor") || "web-ui" : "web-ui",
  );
  const [ruleChangeLog, setRuleChangeLog] = useState<
    Array<{ ts: string; action: string; file: string; actor: string }>
  >([]);
  const [ruleGovSecret, setRuleGovSecret] = useState("");
  const [showFieldCatalog, setShowFieldCatalog] = useState(false);
  const [telemetryRows, setTelemetryRows] = useState<
    Array<{ pack_file: string; rule_id: string; kind: string; hits: number }>
  >([]);
  const [telemetryMeta, setTelemetryMeta] = useState<{ total_hits: number; since_unix: number } | null>(null);
  const [telemetryLoading, setTelemetryLoading] = useState(false);

  useEffect(() => {
    fetchPacks();
  }, []);

  useEffect(() => {
    syncRuleGovernanceSecret(ruleGovSecret);
  }, [ruleGovSecret]);

  useEffect(() => {
    try {
      localStorage.setItem("tarka.rule_actor", ruleActor.trim() || "web-ui");
    } catch {
      /* ignore */
    }
  }, [ruleActor]);

  useEffect(() => {
    (async () => {
      try {
        const cat = await rulesApi.verticalPacks();
        setVerticalCatalog(cat.vertical_packs ?? {});
      } catch {
        /* optional */
      }
      try {
        const raw = localStorage.getItem(VERTICAL_HISTORY_KEY);
        setVerticalHistory(raw ? JSON.parse(raw) : []);
      } catch {
        setVerticalHistory([]);
      }
    })();
  }, []);

  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(t);
    }
  }, [toast]);

  // ── Data fetching ──────────────────────────────────────────

  async function fetchPacks() {
    setLoading(true);
    try {
      const res = await rulesApi.list();
      const normalized = (res.packs ?? []).map((pack, idx) => normalizeRulePack(pack, idx));
      setPacks(normalized);
      setError(null);
      try {
        const cl = await rulesApi.changeLog(30);
        setRuleChangeLog((cl.items ?? []).slice(0, 15));
      } catch {
        setRuleChangeLog([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load rules");
    } finally {
      setLoading(false);
    }
  }

  async function refreshTelemetry() {
    setTelemetryLoading(true);
    try {
      const t = await rulesApi.telemetry();
      setTelemetryRows((t.rows ?? []).slice(0, 40));
      setTelemetryMeta({ total_hits: t.total_hits ?? 0, since_unix: t.since_unix ?? 0 });
    } catch {
      setTelemetryRows([]);
      setTelemetryMeta(null);
    } finally {
      setTelemetryLoading(false);
    }
  }

  useEffect(() => {
    void refreshTelemetry();
  }, []);

  function handleExportPacks() {
    const cleaned = packs.map((p) => {
      const copy = structuredClone(p) as unknown as Record<string, unknown>;
      delete copy._file;
      return copy;
    });
    const blob = new Blob([JSON.stringify(cleaned, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `tarka-rule-packs-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    setToast("Exported rule packs JSON");
  }

  // ── Pack selection ─────────────────────────────────────────

  function selectPack(file: string) {
    if (dirty && !confirm("You have unsaved changes. Discard?")) return;
    const pack = packs.find((p) => packFile(p) === file);
    if (!pack) return;
    setSelectedFile(file);
    setEditingPack(structuredClone(pack));
    setDirty(false);
    setTagInputs({});
  }

  function mutate(fn: (p: RulePack) => void) {
    setEditingPack((prev) => {
      if (!prev) return prev;
      const copy = structuredClone(prev);
      fn(copy);
      return copy;
    });
    setDirty(true);
  }

  // ── CRUD ───────────────────────────────────────────────────

  async function handleCreatePack() {
    const name = newPackName.trim();
    if (!name) return;
    setCreating(true);
    try {
      await rulesApi.create({ name, rules: [], tag_rules: [] });
      await rulesApi.reload();
      await fetchPacks();
      setShowCreateModal(false);
      setNewPackName("");
      setToast(`Pack "${name}" created`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setCreating(false);
    }
  }

  async function handleDeletePack(file: string) {
    setDeleting(true);
    try {
      await rulesApi.deletePack(file);
      await rulesApi.reload();
      await fetchPacks();
      if (selectedFile === file) {
        setSelectedFile(null);
        setEditingPack(null);
        setDirty(false);
      }
      setDeleteConfirm(null);
      setToast("Pack deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }

  async function handleSavePack() {
    if (!editingPack || !selectedFile) return;
    setSaving(true);
    try {
      await rulesApi.update(selectedFile, {
        name: editingPack.name,
        rules: editingPack.rules,
        tag_rules: editingPack.tag_rules ?? [],
      });
      await rulesApi.reload();
      await fetchPacks();
      setDirty(false);
      setToast("Pack saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleReload() {
    setReloading(true);
    try {
      await rulesApi.reload();
      await fetchPacks();
      setToast("Rules reloaded");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reload failed");
    } finally {
      setReloading(false);
    }
  }

  async function handleInstallVerticalPack(vertical: string) {
    setInstallingVertical(vertical);
    try {
      await rulesApi.installVerticalPack(vertical, true);
      await rulesApi.reload();
      await fetchPacks();
      setToast(`Installed vertical pack: ${vertical}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Vertical install failed");
    } finally {
      setInstallingVertical(null);
    }
  }

  async function handleRunVerticalBenchmark(vertical: string) {
    setBenchmarkingVertical(vertical);
    try {
      const resp = await simulation.benchmarkVertical({
        scenario: benchmarkScenario,
        vertical,
      });
      const data = resp as {
        scenario: string;
        vertical: string;
        delta?: Record<string, unknown>;
        baseline?: Record<string, unknown>;
        vertical_pack?: Record<string, unknown>;
      };
      const existingRaw = localStorage.getItem(VERTICAL_HISTORY_KEY);
      const existing = existingRaw ? (JSON.parse(existingRaw) as Array<{
        ts: string;
        scenario: string;
        vertical: string;
        baseline_f1: number;
        vertical_f1: number;
        delta_f1: number;
      }>) : [];
      const entry = {
        ts: new Date().toISOString(),
        scenario: data.scenario,
        vertical: data.vertical,
        baseline_f1: Number(data.baseline?.f1_score ?? 0),
        vertical_f1: Number(data.vertical_pack?.f1_score ?? 0),
        delta_f1: Number(data.delta?.f1_score ?? 0),
      };
      const next = [entry, ...existing].slice(0, 20);
      localStorage.setItem(VERTICAL_HISTORY_KEY, JSON.stringify(next));
      setVerticalHistory(next);
      setToast(`Benchmark completed: ${vertical} (${benchmarkScenario})`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Benchmark failed");
    } finally {
      setBenchmarkingVertical(null);
    }
  }

  async function loadLineage() {
    setLineageBusy(true);
    try {
      const res = await ml.modelLineage(lineageModelName.trim(), lineageVersion);
      setLineageHash(res.lineage.sha256);
      setError(null);
    } catch (e) {
      setLineageHash("");
      setError(e instanceof Error ? e.message : "Lineage lookup failed");
    } finally {
      setLineageBusy(false);
    }
  }

  // ── Rule mutations ─────────────────────────────────────────

  function addRule(template?: RuleTemplate) {
    mutate((p) => {
      p.rules.push({
        id: uid(),
        description: template?.rule.description ?? "",
        score_delta: template?.rule.score_delta ?? 0,
        tags: template?.rule.tags ? [...template.rule.tags] : [],
        when: template?.rule.when ? structuredClone(template.rule.when) : [],
        enabled: true,
      });
    });
  }

  function removeRule(idx: number) {
    mutate((p) => p.rules.splice(idx, 1));
  }

  function updateRule(idx: number, patch: Partial<RuleDetail>) {
    mutate((p) => {
      p.rules[idx] = { ...p.rules[idx], ...patch };
    });
  }

  function addCondition(ri: number) {
    mutate((p) => {
      p.rules[ri].when.push({ field: "amount", op: "gte", value: 0 });
    });
  }

  function removeCondition(ri: number, ci: number) {
    mutate((p) => p.rules[ri].when.splice(ci, 1));
  }

  function updateCondition(
    ri: number,
    ci: number,
    patch: Partial<{ field: string; op: string; value: unknown }>,
  ) {
    mutate((p) => {
      const cond = p.rules[ri].when[ci];
      Object.assign(cond, patch);
      if (patch.op && BOOLEAN_OPS.has(patch.op)) {
        cond.value = patch.op === "is_true";
      }
    });
  }

  function addTag(ri: number, tag: string) {
    const t = tag.trim().toLowerCase().replace(/\s+/g, "_");
    if (!t) return;
    mutate((p) => {
      const tags = p.rules[ri].tags ?? [];
      if (!tags.includes(t)) tags.push(t);
      p.rules[ri].tags = tags;
    });
    setTagInputs((prev) => ({ ...prev, [ri]: "" }));
  }

  function removeTag(ri: number, tag: string) {
    mutate((p) => {
      p.rules[ri].tags = (p.rules[ri].tags ?? []).filter((x) => x !== tag);
    });
  }

  // ── Simulation ─────────────────────────────────────────────

  async function handleSimulate() {
    setSimulating(true);
    setSimError(null);
    setSimResult(null);
    try {
      const payload: DecisionRequest = JSON.parse(simPayload);
      const result = await rulesApi.simulate(payload);
      setSimResult(result);
    } catch (e) {
      setSimError(e instanceof Error ? e.message : "Simulation failed");
    } finally {
      setSimulating(false);
    }
  }

  // ── Render ─────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col animate-fade-in">
      {/* ── Top bar ─────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-surface-700 shrink-0 gap-4">
        <PageTitle module="rules">Rule Builder</PageTitle>
        <div className="flex items-center gap-2 shrink-0">
          {dirty && (
            <span className="text-xs text-amber-400 font-medium mr-1">
              ● Unsaved
            </span>
          )}
          {toast && (
            <span className="text-xs text-green-400 font-medium mr-1">
              ✓ {toast}
            </span>
          )}
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-3 py-1.5 bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium rounded-lg transition-colors"
          >
            + Create Pack
          </button>
          <button
            onClick={handleReload}
            disabled={reloading}
            className="px-3 py-1.5 bg-surface-700 hover:bg-surface-600 disabled:opacity-50 text-gray-300 text-sm font-medium rounded-lg transition-colors"
          >
            {reloading ? "Reloading…" : "Reload"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-6 mt-3 bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm flex items-center justify-between shrink-0">
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
            className="ml-4 text-red-400 hover:text-red-300"
          >
            ×
          </button>
        </div>
      )}

      <div className="mx-6 mt-3 flex flex-col gap-3 text-xs text-gray-400">
        <div className="flex flex-col lg:flex-row lg:flex-wrap gap-3 lg:items-center">
          <label className="flex items-center gap-2 shrink-0">
            <span className="text-gray-500 whitespace-nowrap">Change actor (X-Actor)</span>
            <input
              value={ruleActor}
              onChange={(e) => setRuleActor(e.target.value)}
              className="bg-surface-800 border border-surface-600 rounded px-2 py-1 text-gray-200 font-mono max-w-[16rem]"
              placeholder="web-ui"
            />
          </label>
          <label className="flex items-center gap-2 shrink-0 min-w-0 flex-1">
            <span className="text-gray-500 whitespace-nowrap" title="When RULE_GOVERNANCE_SECRET is set on the API">
              Governance secret
            </span>
            <input
              type="password"
              value={ruleGovSecret}
              onChange={(e) => setRuleGovSecret(e.target.value)}
              className="bg-surface-800 border border-surface-600 rounded px-2 py-1 text-gray-200 font-mono flex-1 min-w-[8rem] max-w-md"
              placeholder="X-Rule-Governance-Secret (optional)"
              autoComplete="off"
            />
          </label>
          <button
            type="button"
            onClick={() => setShowFieldCatalog((v) => !v)}
            className="text-left px-2 py-1 rounded border border-surface-600 hover:bg-surface-800 text-gray-300 shrink-0"
          >
            {showFieldCatalog ? "Hide" : "Show"} field catalog (N1)
          </button>
          <button
            type="button"
            onClick={() => void handleExportPacks()}
            className="px-2 py-1 rounded border border-surface-600 hover:bg-surface-800 text-gray-300 shrink-0"
          >
            Export packs JSON
          </button>
          <button
            type="button"
            onClick={() => void refreshTelemetry()}
            disabled={telemetryLoading}
            className="px-2 py-1 rounded border border-brand-700 hover:bg-brand-900/40 text-brand-300 shrink-0 disabled:opacity-50"
          >
            {telemetryLoading ? "Refreshing…" : "Refresh rule telemetry"}
          </button>
        </div>
        {showFieldCatalog && (
          <div className="border border-surface-700 rounded-lg p-3 bg-surface-900/60 grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {FIELD_CATALOG.map((cat) => (
              <div key={cat.category}>
                <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">{cat.category}</div>
                <ul className="flex flex-wrap gap-1">
                  {cat.fields.map((f) => (
                    <li key={f}>
                      <code className="text-[11px] px-1.5 py-0.5 bg-surface-800 rounded text-gray-300">{f}</code>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
        {(telemetryMeta || telemetryRows.length > 0) && (
          <div className="border border-surface-700 rounded-lg px-3 py-2 bg-surface-900/50">
            <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
              Rule hit telemetry (since API process start, N3–N4)
            </div>
            {telemetryMeta && (
              <p className="text-[11px] text-gray-500 mb-2 font-mono">
                Total hits: {telemetryMeta.total_hits} · Prometheus: tarka_json_rule_hits_total
              </p>
            )}
            {telemetryRows.length === 0 ? (
              <p className="text-[11px] text-gray-600">No rule hits recorded yet — run evaluations against this API.</p>
            ) : (
              <ul className="max-h-24 overflow-y-auto space-y-0.5 font-mono text-[11px]">
                {telemetryRows.map((r, i) => (
                  <li key={`${r.pack_file}-${r.rule_id}-${r.kind}-${i}`} className="truncate text-gray-400">
                    <span className="text-brand-400">{r.hits}</span>× {r.pack_file} · {r.rule_id}{" "}
                    <span className="text-gray-600">({r.kind})</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {ruleChangeLog.length > 0 && (
          <div className="flex-1 min-w-0 border border-surface-700 rounded-lg px-3 py-2 bg-surface-900/50">
            <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Recent pack changes</div>
            <ul className="space-y-0.5 max-h-20 overflow-y-auto font-mono text-[11px]">
              {ruleChangeLog.map((e, i) => (
                <li key={`${e.ts}-${e.file}-${i}`} className="truncate">
                  <span className="text-gray-500">{e.ts.slice(0, 19)}</span>{" "}
                  <span className="text-brand-300">{e.action}</span> {e.file}{" "}
                  <span className="text-gray-600">({e.actor})</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* ── Body ────────────────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">
        {/* ── Sidebar ─────────────────────────────────────── */}
        <aside className="w-72 shrink-0 border-r border-surface-700 flex flex-col overflow-y-auto">
          <div className="px-4 pt-4 pb-2">
            <h2 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
              Rule Packs
            </h2>
          </div>
          <nav className="flex-1 px-2 pb-4 space-y-0.5">
            {packs.map((pack) => {
              const file = packFile(pack);
              const sel = selectedFile === file;
              const uniqueTags = new Set(
                pack.rules.flatMap((r) => r.tags ?? []),
              ).size;
              return (
                <div
                  key={file}
                  className={`group rounded-lg transition-colors ${sel ? "bg-surface-700" : "hover:bg-surface-800/60"}`}
                >
                  <button
                    onClick={() => selectPack(file)}
                    className="w-full text-left px-3 py-2.5"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className={`text-sm font-medium truncate ${sel ? "text-gray-100" : "text-gray-300"}`}
                      >
                        {pack.name}
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteConfirm(file);
                        }}
                        className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-500 hover:text-red-400 transition-all"
                        title="Delete pack"
                      >
                        <TrashIcon size={14} />
                      </button>
                    </div>
                    <div className="flex gap-3 mt-1 text-[11px] text-gray-500">
                      <span>{pack.rules.length} rules</span>
                      <span>{uniqueTags} tags</span>
                      {pack.version != null && <span>v{pack.version}</span>}
                    </div>
                  </button>
                </div>
              );
            })}
            {packs.length === 0 && (
              <p className="text-xs text-gray-500 text-center py-10">
                No rule packs loaded
              </p>
            )}
          </nav>

          <div className="px-3 pb-4 border-t border-surface-700">
            <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mt-3 mb-2">
              Vertical Packs
            </h3>
            <div className="mb-2">
              <label className="text-[10px] text-gray-500 block mb-1">Benchmark Scenario</label>
              <select
                value={benchmarkScenario}
                onChange={(e) => setBenchmarkScenario(e.target.value)}
                className="w-full bg-surface-800 border border-surface-700 text-gray-300 text-xs rounded px-2 py-1"
              >
                <option value="baseline">baseline</option>
                <option value="high_fraud">high_fraud</option>
                <option value="bot_attack">bot_attack</option>
                <option value="account_takeover">account_takeover</option>
                <option value="money_mule">money_mule</option>
              </select>
            </div>
            <div className="space-y-2">
              {Object.entries(verticalCatalog).map(([key, v]) => {
                const installed = packs.some((p) => packFile(p) === `vertical_${key}.json`);
                return (
                  <div key={key} className="bg-surface-800 border border-surface-700 rounded-lg p-2">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-xs text-gray-200 font-medium">{v.name}</div>
                        <div className="text-[10px] text-gray-500">{v.rules} rules · v{v.version}</div>
                      </div>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                        installed ? "bg-green-500/20 text-green-400" : "bg-amber-500/20 text-amber-400"
                      }`}>
                        {installed ? "Installed" : "Not Installed"}
                      </span>
                    </div>
                    <button
                      onClick={() => void handleInstallVerticalPack(key)}
                      disabled={installingVertical === key}
                      className="mt-2 w-full text-xs px-2 py-1 rounded bg-brand-700 hover:bg-brand-600 disabled:opacity-50 text-white"
                    >
                      {installingVertical === key ? "Installing..." : "Install / Update"}
                    </button>
                    <button
                      onClick={() => void handleRunVerticalBenchmark(key)}
                      disabled={benchmarkingVertical === key}
                      className="mt-1 w-full text-xs px-2 py-1 rounded bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white"
                    >
                      {benchmarkingVertical === key ? "Benchmarking..." : "Run benchmark now"}
                    </button>
                  </div>
                );
              })}
              {Object.keys(verticalCatalog).length === 0 && (
                <div className="text-[11px] text-gray-500">No vertical packs catalog loaded.</div>
              )}
            </div>

            <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mt-4 mb-2">
              Last Benchmark History
            </h3>
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {verticalHistory.map((h, i) => (
                <div key={`${h.ts}-${i}`} className="bg-surface-800 border border-surface-700 rounded p-2">
                  <div className="text-[10px] text-gray-400">{new Date(h.ts).toLocaleString()}</div>
                  <div className="text-xs text-gray-200">{h.vertical} · {h.scenario}</div>
                  <div className={`text-[11px] font-mono ${h.delta_f1 >= 0 ? "text-green-400" : "text-red-400"}`}>
                    ΔF1 {h.delta_f1 >= 0 ? "+" : ""}{h.delta_f1.toFixed(4)}
                  </div>
                </div>
              ))}
              {verticalHistory.length === 0 && (
                <div className="text-[11px] text-gray-500">No benchmark runs yet.</div>
              )}
            </div>

            <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mt-4 mb-2">
              Model Lineage
            </h3>
            <div className="bg-surface-800 border border-surface-700 rounded p-2 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <input
                  value={lineageModelName}
                  onChange={(e) => setLineageModelName(e.target.value)}
                  placeholder="model name"
                  className="bg-surface-900 border border-surface-700 text-gray-300 text-xs rounded px-2 py-1"
                />
                <input
                  value={lineageVersion}
                  onChange={(e) => setLineageVersion(Number(e.target.value) || 1)}
                  type="number"
                  min={1}
                  className="bg-surface-900 border border-surface-700 text-gray-300 text-xs rounded px-2 py-1"
                />
              </div>
              <button
                onClick={() => void loadLineage()}
                disabled={lineageBusy}
                className="w-full text-xs px-2 py-1 rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 text-white"
              >
                {lineageBusy ? "Loading..." : "Fetch lineage hash"}
              </button>
              <div className="text-[11px] text-gray-400 break-all">
                {lineageHash ? lineageHash : "No lineage loaded yet."}
              </div>
            </div>
          </div>
        </aside>

        {/* ── Main content ────────────────────────────────── */}
        <main className="flex-1 overflow-y-auto">
          {editingPack ? (
            <div className="p-6 space-y-5 max-w-5xl">
              {/* Pack header */}
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-gray-100">
                    {editingPack.name}
                  </h2>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {selectedFile} · {editingPack.rules.length} rule
                    {editingPack.rules.length !== 1 && "s"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowTemplates((v) => !v)}
                    className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${showTemplates ? "bg-brand-600/20 text-brand-400 border border-brand-500/40" : "bg-surface-700 hover:bg-surface-600 text-gray-300"}`}
                  >
                    Templates
                  </button>
                  <button
                    onClick={handleSavePack}
                    disabled={saving || !dirty}
                    className="px-4 py-1.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    {saving ? "Saving…" : "Save Pack"}
                  </button>
                </div>
              </div>

              {/* Templates */}
              {showTemplates && (
                <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 animate-fade-in">
                  <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                    Quick-Add Templates
                  </h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-2">
                    {RULE_TEMPLATES.map((t) => (
                      <button
                        key={t.name}
                        onClick={() => addRule(t)}
                        className="text-left p-3 bg-surface-800 hover:bg-surface-700 rounded-lg transition-colors group"
                      >
                        <div className="text-sm font-medium text-gray-200 group-hover:text-gray-100">
                          {t.name}
                        </div>
                        <div className="text-[11px] text-gray-500 mt-0.5 leading-snug">
                          {t.description}
                        </div>
                        <div className="text-xs text-brand-400 mt-1.5 font-mono">
                          +{t.rule.score_delta} pts
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Rules */}
              <div className="space-y-4">
                {editingPack.rules.map((rule, ri) => (
                  <RuleCard
                    key={rule.id ?? ri}
                    rule={rule}
                    onUpdate={(p) => updateRule(ri, p)}
                    onRemove={() => removeRule(ri)}
                    onAddCondition={() => addCondition(ri)}
                    onRemoveCondition={(ci) => removeCondition(ri, ci)}
                    onUpdateCondition={(ci, p) => updateCondition(ri, ci, p)}
                    onAddTag={(tag) => addTag(ri, tag)}
                    onRemoveTag={(tag) => removeTag(ri, tag)}
                    tagInput={tagInputs[ri] ?? ""}
                    onTagInputChange={(v) =>
                      setTagInputs((prev) => ({ ...prev, [ri]: v }))
                    }
                  />
                ))}
              </div>

              <button
                onClick={() => addRule()}
                className="w-full py-3 border-2 border-dashed border-surface-600 hover:border-brand-500/60 text-gray-500 hover:text-brand-400 rounded-xl text-sm font-medium transition-colors"
              >
                + Add Rule
              </button>

              {/* Simulation */}
              <SimulationPanel
                payload={simPayload}
                onPayloadChange={setSimPayload}
                result={simResult}
                simError={simError}
                simulating={simulating}
                onSimulate={handleSimulate}
              />
            </div>
          ) : (
            <div className="flex items-center justify-center h-full">
              <div className="text-center text-gray-500">
                <div className="text-5xl mb-4 opacity-20">⚡</div>
                <p className="text-sm font-medium">
                  Select a rule pack to start editing
                </p>
                <p className="text-xs mt-1 text-gray-600">
                  or create a new one
                </p>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* ── Create Pack Modal ──────────────────────────────── */}
      {showCreateModal && (
        <Modal onClose={() => setShowCreateModal(false)}>
          <h3 className="text-lg font-semibold text-gray-100 mb-4">
            Create Rule Pack
          </h3>
          <input
            value={newPackName}
            onChange={(e) => setNewPackName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreatePack()}
            placeholder="Pack name (e.g. payment_fraud)"
            className="w-full bg-surface-800 border border-surface-600 text-gray-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
            autoFocus
          />
          <div className="flex justify-end gap-2 mt-4">
            <button
              onClick={() => setShowCreateModal(false)}
              className="px-3 py-1.5 text-gray-400 hover:text-gray-200 text-sm transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleCreatePack}
              disabled={creating || !newPackName.trim()}
              className="px-4 py-1.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {creating ? "Creating…" : "Create"}
            </button>
          </div>
        </Modal>
      )}

      {/* ── Delete Confirm Modal ───────────────────────────── */}
      {deleteConfirm && (
        <Modal onClose={() => setDeleteConfirm(null)}>
          <h3 className="text-lg font-semibold text-gray-100 mb-2">
            Delete Pack
          </h3>
          <p className="text-sm text-gray-400 mb-4">
            Permanently delete{" "}
            <span className="text-gray-200 font-medium">{deleteConfirm}</span>?
            This cannot be undone.
          </p>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setDeleteConfirm(null)}
              className="px-3 py-1.5 text-gray-400 hover:text-gray-200 text-sm transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => handleDeletePack(deleteConfirm)}
              disabled={deleting}
              className="px-4 py-1.5 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {deleting ? "Deleting…" : "Delete"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── RuleCard ─────────────────────────────────────────────────────────

interface RuleCardProps {
  rule: RuleDetail;
  onUpdate: (patch: Partial<RuleDetail>) => void;
  onRemove: () => void;
  onAddCondition: () => void;
  onRemoveCondition: (ci: number) => void;
  onUpdateCondition: (
    ci: number,
    patch: Partial<{ field: string; op: string; value: unknown }>,
  ) => void;
  onAddTag: (tag: string) => void;
  onRemoveTag: (tag: string) => void;
  tagInput: string;
  onTagInputChange: (v: string) => void;
}

function RuleCard({
  rule,
  onUpdate,
  onRemove,
  onAddCondition,
  onRemoveCondition,
  onUpdateCondition,
  onAddTag,
  onRemoveTag,
  tagInput,
  onTagInputChange,
}: RuleCardProps) {
  const enabled = rule.enabled !== false;

  function handleTagKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      onAddTag(tagInput);
    }
  }

  return (
    <div
      className={`bg-surface-900 border rounded-xl overflow-hidden transition-colors ${enabled ? "border-surface-700" : "border-surface-700/50 opacity-60"}`}
    >
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-surface-700/60">
        <button
          onClick={() => onUpdate({ enabled: !enabled })}
          title={enabled ? "Disable rule" : "Enable rule"}
          className={`w-8 h-[18px] rounded-full relative shrink-0 transition-colors ${enabled ? "bg-brand-600" : "bg-surface-600"}`}
        >
          <span
            className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-all ${enabled ? "left-[16px]" : "left-[2px]"}`}
          />
        </button>

        <input
          value={rule.id}
          onChange={(e) => onUpdate({ id: e.target.value })}
          className="bg-transparent text-sm font-mono text-gray-300 border-none outline-none w-40 shrink-0"
          placeholder="rule_id"
        />

        <input
          value={rule.description ?? ""}
          onChange={(e) => onUpdate({ description: e.target.value })}
          className="flex-1 bg-transparent text-sm text-gray-400 border-none outline-none placeholder-gray-600"
          placeholder="Description…"
        />

        <button
          onClick={onRemove}
          className="text-gray-500 hover:text-red-400 transition-colors p-1"
          title="Remove rule"
        >
          <TrashIcon size={15} />
        </button>
      </div>

      <div className="px-4 py-3 space-y-3">
        {/* Score delta */}
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500 w-20 shrink-0">
            Score delta
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() =>
                onUpdate({ score_delta: (rule.score_delta ?? 0) - 1 })
              }
              className="w-7 h-7 flex items-center justify-center rounded bg-surface-800 hover:bg-surface-700 text-gray-400 text-sm transition-colors"
            >
              −
            </button>
            <input
              type="number"
              value={rule.score_delta ?? 0}
              onChange={(e) =>
                onUpdate({ score_delta: parseInt(e.target.value) || 0 })
              }
              className="w-16 text-center bg-surface-800 border border-surface-600 text-gray-200 text-sm font-mono rounded px-1 py-1 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
            <button
              onClick={() =>
                onUpdate({ score_delta: (rule.score_delta ?? 0) + 1 })
              }
              className="w-7 h-7 flex items-center justify-center rounded bg-surface-800 hover:bg-surface-700 text-gray-400 text-sm transition-colors"
            >
              +
            </button>
            <span
              className={`ml-2 text-xs font-mono ${(rule.score_delta ?? 0) > 0 ? "text-red-400" : (rule.score_delta ?? 0) < 0 ? "text-green-400" : "text-gray-500"}`}
            >
              {(rule.score_delta ?? 0) > 0 ? "+" : ""}
              {rule.score_delta ?? 0} pts
            </span>
          </div>
        </div>

        {/* Tags */}
        <div className="flex items-start gap-3">
          <span className="text-xs text-gray-500 w-20 shrink-0 pt-1">
            Tags
          </span>
          <div className="flex flex-wrap items-center gap-1.5">
            {(rule.tags ?? []).map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 px-2 py-0.5 bg-surface-800 text-gray-300 text-xs rounded-md"
              >
                {tag}
                <button
                  onClick={() => onRemoveTag(tag)}
                  className="text-gray-500 hover:text-red-400 transition-colors"
                >
                  ×
                </button>
              </span>
            ))}
            <input
              value={tagInput}
              onChange={(e) => onTagInputChange(e.target.value)}
              onKeyDown={handleTagKey}
              onBlur={() => tagInput && onAddTag(tagInput)}
              placeholder="add tag…"
              className="w-24 bg-transparent text-xs text-gray-400 outline-none placeholder-gray-600"
            />
          </div>
        </div>

        {/* Conditions */}
        <div className="space-y-2">
          <span className="text-xs text-gray-500">Conditions</span>
          {rule.when.length === 0 && (
            <p className="text-[11px] text-gray-600 italic ml-1">
              No conditions — rule will never fire
            </p>
          )}
          {rule.when.map((cond, ci) => (
            <ConditionRow
              key={ci}
              condition={cond}
              isFirst={ci === 0}
              onUpdate={(p) => onUpdateCondition(ci, p)}
              onRemove={() => onRemoveCondition(ci)}
            />
          ))}
          <button
            onClick={onAddCondition}
            className="text-xs text-brand-400 hover:text-brand-300 transition-colors mt-1"
          >
            + Add Condition
          </button>
        </div>
      </div>
    </div>
  );
}

// ── ConditionRow ─────────────────────────────────────────────────────

function ConditionRow({
  condition,
  isFirst,
  onUpdate,
  onRemove,
}: {
  condition: { field: string; op: string; value: unknown };
  isFirst: boolean;
  onUpdate: (patch: Partial<{ field: string; op: string; value: unknown }>) => void;
  onRemove: () => void;
}) {
  const isBool = BOOLEAN_OPS.has(condition.op);
  const isIn = condition.op === "in";

  function handleValueChange(raw: string) {
    if (isIn) {
      const parts = raw.split(",").map((s) => parseValue(s.trim()));
      onUpdate({ value: parts });
    } else {
      onUpdate({ value: parseValue(raw) });
    }
  }

  const displayValue = isIn
    ? Array.isArray(condition.value)
      ? (condition.value as unknown[]).join(", ")
      : String(condition.value ?? "")
    : String(condition.value ?? "");

  return (
    <div className="flex items-center gap-2 group">
      <span className="w-8 text-[10px] text-gray-600 text-right shrink-0 font-medium">
        {isFirst ? "IF" : "AND"}
      </span>

      {/* Field */}
      <div className="relative">
        <input
          list="rule-fields"
          value={condition.field}
          onChange={(e) => onUpdate({ field: e.target.value })}
          className="w-44 bg-surface-800 border border-surface-600 text-gray-200 text-xs rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
          placeholder="field"
        />
        <datalist id="rule-fields">
          {COMMON_FIELDS.map((f) => (
            <option key={f} value={f} />
          ))}
        </datalist>
      </div>

      {/* Operator */}
      <select
        value={condition.op}
        onChange={(e) => onUpdate({ op: e.target.value })}
        className="w-40 bg-surface-800 border border-surface-600 text-gray-200 text-xs rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500 appearance-none"
      >
        {OPERATORS.map((op) => (
          <option key={op.value} value={op.value}>
            {op.label}
          </option>
        ))}
      </select>

      {/* Value */}
      {!isBool && (
        <input
          value={displayValue}
          onChange={(e) => handleValueChange(e.target.value)}
          placeholder={isIn ? "val1, val2, …" : "value"}
          className="flex-1 min-w-[80px] bg-surface-800 border border-surface-600 text-gray-200 text-xs font-mono rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
      )}
      {isBool && <div className="flex-1" />}

      <button
        onClick={onRemove}
        className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition-all p-1"
        title="Remove condition"
      >
        ×
      </button>
    </div>
  );
}

// ── SimulationPanel ──────────────────────────────────────────────────

function SimulationPanel({
  payload,
  onPayloadChange,
  result,
  simError,
  simulating,
  onSimulate,
}: {
  payload: string;
  onPayloadChange: (v: string) => void;
  result: DecisionResponse | null;
  simError: string | null;
  simulating: boolean;
  onSimulate: () => void;
}) {
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
      <h3 className="text-sm font-semibold text-gray-300 mb-4">
        Rule Simulation
      </h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Payload editor */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">
            Test Payload (JSON)
          </label>
          <textarea
            value={payload}
            onChange={(e) => onPayloadChange(e.target.value)}
            rows={10}
            spellCheck={false}
            className="w-full bg-surface-800 border border-surface-600 text-gray-300 text-sm font-mono rounded-lg px-4 py-3 focus:outline-none focus:ring-1 focus:ring-brand-500 resize-none"
          />
          <button
            onClick={onSimulate}
            disabled={simulating}
            className="mt-3 px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {simulating ? "Running…" : "Simulate"}
          </button>
        </div>

        {/* Result */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">Result</label>

          {simError && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm">
              {simError}
            </div>
          )}

          {result && (
            <div className="bg-surface-800 rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-4">
                <span className="text-xs text-gray-500">Decision</span>
                <DecisionPill decision={result.decision} />
              </div>
              <div>
                <span className="text-xs text-gray-500">Score</span>
                <p
                  className={`text-xl font-bold ${result.score >= 70 ? "text-red-400" : result.score >= 40 ? "text-amber-400" : "text-green-400"}`}
                >
                  {result.score}
                </p>
              </div>
              <div>
                <span className="text-xs text-gray-500">Rules Fired</span>
                <div className="mt-1 space-y-1">
                  {result.rule_hits.map((hit) => (
                    <div key={hit} className="text-sm text-gray-300 font-mono">
                      {hit}
                    </div>
                  ))}
                  {result.rule_hits.length === 0 && (
                    <p className="text-xs text-gray-500">No rules fired</p>
                  )}
                </div>
              </div>
              {result.tags && result.tags.length > 0 && (
                <div>
                  <span className="text-xs text-gray-500">Tags Applied</span>
                  <div className="flex flex-wrap gap-1.5 mt-1">
                    {result.tags.map((tag) => (
                      <span
                        key={tag}
                        className="px-2 py-0.5 bg-surface-700 text-gray-300 text-xs rounded"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {!result && !simError && (
            <div className="bg-surface-800 rounded-lg p-8 text-center text-gray-500 text-sm">
              Enter a payload and click Simulate
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Small Components ─────────────────────────────────────────────────

function Modal({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-6 w-full max-w-md shadow-2xl animate-fade-in">
        {children}
      </div>
    </div>
  );
}

function DecisionPill({ decision }: { decision: string }) {
  const styles: Record<string, string> = {
    allow: "bg-green-500/20 text-green-400",
    review: "bg-amber-500/20 text-amber-400",
    deny: "bg-red-500/20 text-red-400",
  };
  return (
    <span
      className={`px-3 py-1 rounded-full text-sm font-semibold capitalize ${styles[decision] ?? "bg-gray-500/20 text-gray-400"}`}
    >
      {decision}
    </span>
  );
}

function TrashIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 4h12M5.333 4V2.667a1.333 1.333 0 011.334-1.334h2.666a1.333 1.333 0 011.334 1.334V4m2 0v9.333a1.333 1.333 0 01-1.334 1.334H4.667a1.333 1.333 0 01-1.334-1.334V4h9.334z" />
    </svg>
  );
}
