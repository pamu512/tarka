import { useEffect, useMemo, useState } from "react";
import { integrations } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { safeExternalHref } from "../utils/externalLinks";

type Provider = {
  id: string;
  name: string;
  category: string;
  type: string;
  required_config_fields?: string[];
  doc_url: string;
};

const CATEGORY_LABELS: Record<string, string> = {
  kyc: "KYC",
  device_intelligence: "Device Intelligence",
  ip_intelligence: "IP Intelligence",
  phone_number: "Phone Number",
  social_media: "Social Media",
  sanctions: "Sanctions",
  payments: "Payments",
  dispute_management: "Dispute Management",
  early_alerts: "Early Alerts",
  crm: "CRM",
};

export default function Integrations() {
  const tenantId = "demo";
  const [providers, setProviders] = useState<Provider[]>([]);
  const [installed, setInstalled] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string>("");
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [message, setMessage] = useState<string>("");
  const [testBusyId, setTestBusyId] = useState<string>("");
  const [testResults, setTestResults] = useState<Record<string, { status: string; latency_ms: number; missing_fields: string[] }>>({});
  const [readiness, setReadiness] = useState<{
    readiness_score: number;
    covered_categories: number;
    total_categories: number;
    coverage: Record<string, { installed: boolean; count: number }>;
  } | null>(null);
  const [healthScore, setHealthScore] = useState<number>(0);
  const [kmsStatus, setKmsStatus] = useState<{ provider: string; active_key_id: string; config_valid: boolean } | null>(null);
  const [rotationJobs, setRotationJobs] = useState<Array<{ id: string; status: string; processed: number; rotated: number; failed: number }>>([]);
  const [slo, setSlo] = useState<{ availability_target: number; latency_target_ms_p95: number; error_budget_window_days: number; current: { kms_provider: string; rotation_jobs: number; rotation_failures: number } } | null>(null);

  const [requestName, setRequestName] = useState("");
  const [requestCategory, setRequestCategory] = useState("kyc");
  const [requestUseCase, setRequestUseCase] = useState("");
  const [requestGithubUser, setRequestGithubUser] = useState("");
  const [configProviderId, setConfigProviderId] = useState<string>("");
  const [configDraft, setConfigDraft] = useState<Record<string, string>>({});
  const [configMask, setConfigMask] = useState<Record<string, string>>({});

  async function refresh() {
    const [catalog, current, ready, health, kms, jobs, sloStatus] = await Promise.all([
      integrations.catalog(),
      integrations.installed(tenantId),
      integrations.readiness(tenantId),
      integrations.healthMatrix(tenantId),
      integrations.vaultKmsStatus(),
      integrations.vaultRotationJobs(),
      integrations.slo(),
    ]);
    setProviders(catalog.providers);
    const map: Record<string, boolean> = {};
    for (const row of current.installed) {
      const providerId = String(row.provider_id ?? "");
      const status = String(row.status ?? "");
      if (providerId) map[providerId] = status === "enabled";
    }
    setInstalled(map);
    setReadiness({
      readiness_score: ready.readiness_score,
      covered_categories: ready.covered_categories,
      total_categories: ready.total_categories,
      coverage: ready.coverage,
    });
    setHealthScore(health.score);
    setKmsStatus({ provider: kms.provider, active_key_id: kms.active_key_id, config_valid: kms.config_valid });
    setRotationJobs(jobs.jobs.slice(0, 3));
    setSlo(sloStatus);
    const tests: Record<string, { status: string; latency_ms: number; missing_fields: string[] }> = {};
    for (const row of health.rows) {
      tests[row.provider_id] = {
        status: row.status,
        latency_ms: row.latency_ms,
        missing_fields: row.missing_fields,
      };
    }
    setTestResults(tests);
  }

  useEffect(() => {
    (async () => {
      try {
        await refresh();
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const categories = useMemo(() => {
    const values = Array.from(new Set(providers.map((p) => p.category)));
    values.sort();
    return values;
  }, [providers]);

  const filtered = useMemo(
    () => providers.filter((p) => selectedCategory === "all" || p.category === selectedCategory),
    [providers, selectedCategory],
  );

  async function toggleInstall(provider: Provider) {
    setBusyId(provider.id);
    setMessage("");
    try {
      if (installed[provider.id]) {
        await integrations.uninstall(tenantId, provider.id);
        setMessage(`Disabled ${provider.name}`);
      } else {
        await integrations.install(tenantId, provider.id, {});
        setMessage(`Enabled ${provider.name}`);
      }
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Integration update failed");
    } finally {
      setBusyId("");
    }
  }

  async function submitRequest(e: React.FormEvent) {
    e.preventDefault();
    if (!requestName.trim() || !requestUseCase.trim()) return;
    setMessage("");
    try {
      const res = await integrations.requestNew({
        tenant_id: tenantId,
        requested_name: requestName.trim(),
        category: requestCategory,
        use_case: requestUseCase.trim(),
        github_username: requestGithubUser.trim(),
      });
      setMessage(
        res.message ??
          "Request submitted. An administrator must approve it before a prefilled GitHub issue is created for engineering.",
      );
      setRequestName("");
      setRequestUseCase("");
      setRequestGithubUser("");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Failed to submit request");
    }
  }

  async function testConnection(provider: Provider) {
    setTestBusyId(provider.id);
    setMessage("");
    try {
      const res = await integrations.testConnectivity(tenantId, provider.id);
      setTestResults((prev) => ({
        ...prev,
        [provider.id]: {
          status: res.status,
          latency_ms: res.latency_ms,
          missing_fields: res.missing_fields,
        },
      }));
      setMessage(
        res.status === "pass"
          ? `${provider.name} connectivity check passed (${res.latency_ms}ms)`
          : `${provider.name} check failed. Missing: ${res.missing_fields.join(", ") || "unknown"}`,
      );
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Connectivity test failed");
    } finally {
      setTestBusyId("");
    }
  }

  async function openConfigWizard(provider: Provider) {
    setConfigProviderId(provider.id);
    setConfigDraft({});
    try {
      const cfg = await integrations.getConfig(tenantId, provider.id);
      setConfigMask(cfg.masked_config ?? {});
    } catch {
      setConfigMask({});
    }
  }

  async function saveConfig(provider: Provider) {
    try {
      await integrations.configure(tenantId, provider.id, configDraft);
      setMessage(`Saved config for ${provider.name}`);
      setConfigProviderId("");
      setConfigDraft({});
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Failed to save config");
    }
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <PageTitle module="integrations">Integrations</PageTitle>
        <p className="text-sm text-gray-400 mt-1">
          One-click integrations for top enrichment providers, workflows, and CRMs.
        </p>
      </div>

      <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 flex flex-wrap items-center gap-2">
        <button
          className={`px-3 py-1.5 text-xs rounded ${selectedCategory === "all" ? "bg-brand-600 text-white" : "bg-surface-800 text-gray-300"}`}
          onClick={() => setSelectedCategory("all")}
        >
          All
        </button>
        {categories.map((c) => (
          <button
            key={c}
            className={`px-3 py-1.5 text-xs rounded ${selectedCategory === c ? "bg-brand-600 text-white" : "bg-surface-800 text-gray-300"}`}
            onClick={() => setSelectedCategory(c)}
          >
            {CATEGORY_LABELS[c] ?? c}
          </button>
        ))}
      </div>
      {readiness && (
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-gray-200">Next 10x: Integration Readiness</h2>
              <p className="text-xs text-gray-400 mt-1">
                Coverage across KYC, device, IP, phone, social, sanctions, payments, disputes, early alerts, and CRM.
              </p>
            </div>
            <div className="text-right">
              <div className="text-2xl font-bold text-brand-300">{readiness.readiness_score}%</div>
              <div className="text-xs text-gray-400">{readiness.covered_categories}/{readiness.total_categories} categories</div>
              <div className="text-xs text-gray-500 mt-1">Connectivity health {healthScore}%</div>
              {kmsStatus && (
                <div className="text-xs text-gray-500 mt-1">
                  KMS {kmsStatus.provider} key {kmsStatus.active_key_id} {kmsStatus.config_valid ? "OK" : "Invalid"}
                </div>
              )}
              {slo && (
                <div className="text-xs text-gray-500 mt-1">
                  SLO {slo.availability_target}% | p95 {slo.latency_target_ms_p95}ms | budget {slo.error_budget_window_days}d
                </div>
              )}
            </div>
          </div>
          {rotationJobs.length > 0 && (
            <div className="mt-3 pt-3 border-t border-surface-700 space-y-1">
              <div className="text-xs text-gray-400">Recent rotation jobs</div>
              {rotationJobs.map((j) => (
                <div key={j.id} className="text-[11px] text-gray-500">
                  {j.status} | processed {j.processed} | rotated {j.rotated} | failed {j.failed}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {message && <div className="text-xs text-brand-300 bg-brand-900/20 border border-brand-700/40 rounded p-2">{message}</div>}

      {loading ? (
        <div className="text-sm text-gray-400">Loading integrations…</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((p) => {
            const on = Boolean(installed[p.id]);
            const test = testResults[p.id];
            return (
              <div key={p.id} className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-100">{p.name}</h3>
                    <p className="text-xs text-gray-400 mt-1">{CATEGORY_LABELS[p.category] ?? p.category}</p>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border ${on ? "text-emerald-300 border-emerald-700 bg-emerald-900/20" : "text-gray-400 border-surface-600 bg-surface-800"}`}>
                    {on ? "Enabled" : "Not enabled"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  {(() => {
                    const safeDocHref = safeExternalHref(p.doc_url);
                    return safeDocHref ? (
                      <a href={safeDocHref} target="_blank" rel="noreferrer" className="text-xs text-brand-400 hover:text-brand-300">
                        Docs
                      </a>
                    ) : (
                      <span className="text-xs text-gray-500">Docs unavailable</span>
                    );
                  })()}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => openConfigWizard(p)}
                      className="px-3 py-1.5 text-xs rounded bg-indigo-700 hover:bg-indigo-600 text-white"
                    >
                      Configure
                    </button>
                    <button
                      onClick={() => testConnection(p)}
                      disabled={testBusyId === p.id}
                      className="px-3 py-1.5 text-xs rounded bg-emerald-700 hover:bg-emerald-600 text-white disabled:opacity-40"
                    >
                      {testBusyId === p.id ? "Testing..." : "Test"}
                    </button>
                    <button
                      onClick={() => toggleInstall(p)}
                      disabled={busyId === p.id}
                      className="px-3 py-1.5 text-xs rounded bg-surface-700 hover:bg-surface-600 text-gray-200 disabled:opacity-40"
                    >
                      {busyId === p.id ? "Working..." : on ? "Disable" : "Enable"}
                    </button>
                  </div>
                </div>
                {test && (
                  <div className={`text-[11px] rounded px-2 py-1 border ${test.status === "pass" ? "text-emerald-300 border-emerald-800 bg-emerald-900/20" : "text-orange-300 border-orange-800 bg-orange-900/20"}`}>
                    {test.status === "pass"
                      ? `Connectivity OK (${test.latency_ms}ms)`
                      : `Missing config: ${test.missing_fields.join(", ") || "unknown"}`}
                  </div>
                )}
                {configProviderId === p.id && (
                  <div className="rounded border border-surface-600 bg-surface-800 p-2 space-y-2">
                    <div className="text-xs text-gray-300 font-medium">Credential Wizard</div>
                    <p className="text-[11px] text-gray-400">Use either `api_key` OR `username` + `password`.</p>
                    <div>
                      <label className="block text-[11px] text-gray-400 mb-1">
                        api_key {configMask.api_key ? `(saved: ${configMask.api_key})` : ""}
                      </label>
                      <input
                        type="password"
                        placeholder="Enter api_key"
                        value={configDraft.api_key ?? ""}
                        onChange={(e) => setConfigDraft((prev) => ({ ...prev, api_key: e.target.value }))}
                        className="w-full bg-surface-900 border border-surface-600 rounded px-2 py-1 text-xs text-gray-200"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-[11px] text-gray-400 mb-1">
                          username {configMask.username ? `(saved: ${configMask.username})` : ""}
                        </label>
                        <input
                          type="text"
                          placeholder="Enter username"
                          value={configDraft.username ?? ""}
                          onChange={(e) => setConfigDraft((prev) => ({ ...prev, username: e.target.value }))}
                          className="w-full bg-surface-900 border border-surface-600 rounded px-2 py-1 text-xs text-gray-200"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] text-gray-400 mb-1">
                          password {configMask.password ? `(saved: ${configMask.password})` : ""}
                        </label>
                        <input
                          type="password"
                          placeholder="Enter password"
                          value={configDraft.password ?? ""}
                          onChange={(e) => setConfigDraft((prev) => ({ ...prev, password: e.target.value }))}
                          className="w-full bg-surface-900 border border-surface-600 rounded px-2 py-1 text-xs text-gray-200"
                        />
                      </div>
                    </div>
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => setConfigProviderId("")}
                        className="px-2 py-1 text-xs rounded bg-surface-700 text-gray-300"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => saveConfig(p)}
                        className="px-2 py-1 text-xs rounded bg-brand-600 text-white"
                      >
                        Save
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <section className="bg-surface-900 border border-surface-700 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-200">Request other integrations</h2>
        <p className="text-xs text-gray-400 mt-1">
          Submit a request for review. A <strong className="text-gray-300">platform administrator</strong> must approve
          it in <strong className="text-gray-300">Admin → Integration requests</strong> before a prefilled{" "}
          <strong className="text-gray-300">GitHub</strong> new-issue link is generated for developers.
        </p>
        <form onSubmit={submitRequest} className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          <input
            value={requestName}
            onChange={(e) => setRequestName(e.target.value)}
            placeholder="Provider name"
            className="bg-surface-800 border border-surface-600 rounded px-3 py-2 text-sm text-gray-200"
          />
          <select
            value={requestCategory}
            onChange={(e) => setRequestCategory(e.target.value)}
            className="bg-surface-800 border border-surface-600 rounded px-3 py-2 text-sm text-gray-200"
          >
            {Object.entries(CATEGORY_LABELS).map(([id, label]) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>
          <input
            value={requestGithubUser}
            onChange={(e) => setRequestGithubUser(e.target.value)}
            placeholder="GitHub username (optional)"
            className="bg-surface-800 border border-surface-600 rounded px-3 py-2 text-sm text-gray-200"
          />
          <input
            value={requestUseCase}
            onChange={(e) => setRequestUseCase(e.target.value)}
            placeholder="Use case and expected outcomes"
            className="bg-surface-800 border border-surface-600 rounded px-3 py-2 text-sm text-gray-200"
          />
          <div className="md:col-span-2 flex justify-end">
            <button
              type="submit"
              disabled={!requestName.trim() || !requestUseCase.trim()}
              className="px-4 py-2 text-sm rounded bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-white"
            >
              Request Integration
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
