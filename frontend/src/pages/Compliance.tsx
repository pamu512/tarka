import { useEffect, useState, useCallback } from "react";
import { compliance } from "../api/client";
import { PageTitle } from "../components/PageTitle";

// ── Types ────────────────────────────────────────────────────────────

interface PrivacyProfile {
  region: string;
  regulation: string;
  rights: Record<string, boolean>;
  consent_requirements: string[];
  retention_periods: Record<string, string>;
  encryption_requirements: string[];
  cross_border_rules: string[];
  breach_notification_timeline: string;
}

interface CertControl {
  id: string;
  description: string;
  status: "implemented" | "configurable" | "partial";
}

interface CertFramework {
  name: string;
  controls: CertControl[];
}

interface Certifications {
  frameworks: CertFramework[];
}

interface RopaRecord {
  processing_purpose: string;
  data_categories: string[];
  data_subjects: string[];
  recipients: string[];
  retention: string;
  safeguards: string[];
  legal_basis: string;
}

// ── Helpers ──────────────────────────────────────────────────────────

function statusColor(status: string) {
  switch (status) {
    case "implemented":
      return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
    case "configurable":
      return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
    case "partial":
      return "bg-orange-500/20 text-orange-400 border-orange-500/30";
    default:
      return "bg-gray-500/20 text-gray-400 border-gray-500/30";
  }
}

function progressBarColor(status: string) {
  switch (status) {
    case "implemented":
      return "bg-emerald-500";
    case "configurable":
      return "bg-yellow-500";
    case "partial":
      return "bg-orange-500";
    default:
      return "bg-gray-500";
  }
}

function frameworkProgress(controls: CertControl[]) {
  if (controls.length === 0) return { implemented: 0, configurable: 0, partial: 0 };
  const counts = { implemented: 0, configurable: 0, partial: 0 };
  for (const c of controls) {
    if (c.status in counts) counts[c.status as keyof typeof counts]++;
  }
  return {
    implemented: (counts.implemented / controls.length) * 100,
    configurable: (counts.configurable / controls.length) * 100,
    partial: (counts.partial / controls.length) * 100,
  };
}

function integritySummary(bundle: Record<string, unknown> | null): string {
  if (!bundle) return "Not loaded";
  const integrity = bundle.integrity as Record<string, unknown> | undefined;
  const sig = bundle.signature as string | undefined;
  if (!integrity || !sig) return "Unsigned";
  const alg = String(integrity.algorithm ?? "n/a");
  const hash = String(integrity.bundle_hash ?? "");
  return `${alg} | hash ${hash.slice(0, 12)}... | sig ${sig.slice(0, 12)}...`;
}

// ── Component ────────────────────────────────────────────────────────

export default function Compliance() {
  const [regions, setRegions] = useState<Record<string, unknown>>({});
  const [selectedRegion, setSelectedRegion] = useState("");
  const [profile, setProfile] = useState<PrivacyProfile | null>(null);
  const [certifications, setCertifications] = useState<Certifications | null>(null);
  const [ropa, setRopa] = useState<RopaRecord[] | null>(null);

  const [dsarEntityId, setDsarEntityId] = useState("");
  const [dsarType, setDsarType] = useState<"access" | "erasure" | "portability">("access");
  const [dsarResult, setDsarResult] = useState<unknown>(null);
  const [dsarLoading, setDsarLoading] = useState(false);
  const [decisionEvidence, setDecisionEvidence] = useState<Record<string, unknown> | null>(null);
  const [caseEvidence, setCaseEvidence] = useState<Record<string, unknown> | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [decisionVerify, setDecisionVerify] = useState<string>("");
  const [caseVerify, setCaseVerify] = useState<string>("");
  const [decisionKeyId, setDecisionKeyId] = useState<string>("");
  const [caseKeyId, setCaseKeyId] = useState<string>("");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const tenantId = "demo";

  const fetchRegions = useCallback(async () => {
    try {
      const res = await compliance.regions();
      setRegions(res.regions ?? {});
      const keys = Object.keys(res.regions ?? {});
      if (keys.length > 0 && !selectedRegion) setSelectedRegion(keys[0]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load regions");
    } finally {
      setLoading(false);
    }
  }, [selectedRegion]);

  const fetchProfile = useCallback(async (region: string) => {
    if (!region) return;
    try {
      const res = (await compliance.privacyProfile(tenantId, region)) as {
        profile: PrivacyProfile;
        ropa: RopaRecord[];
      };
      setProfile(res.profile ?? (res as unknown as PrivacyProfile));
      setRopa(res.ropa ?? null);
    } catch {
      setProfile(null);
      setRopa(null);
    }
  }, []);

  const fetchCerts = useCallback(async () => {
    try {
      const res = (await compliance.certifications()) as Certifications;
      setCertifications(res);
    } catch {
      setCertifications(null);
    }
  }, []);

  useEffect(() => {
    fetchRegions();
    fetchCerts();
  }, [fetchRegions, fetchCerts]);

  useEffect(() => {
    if (selectedRegion) fetchProfile(selectedRegion);
  }, [selectedRegion, fetchProfile]);

  async function handleDsarSubmit() {
    if (!dsarEntityId.trim()) return;
    setDsarLoading(true);
    setDsarResult(null);
    try {
      let res: unknown;
      switch (dsarType) {
        case "access":
          res = await compliance.dsarAccess(tenantId, dsarEntityId, selectedRegion);
          break;
        case "erasure":
          res = await compliance.dsarErasure(tenantId, dsarEntityId, selectedRegion);
          break;
        case "portability":
          res = await compliance.dsarPortability(tenantId, dsarEntityId, selectedRegion);
          break;
      }
      setDsarResult(res);
    } catch (e) {
      setDsarResult({ error: e instanceof Error ? e.message : "DSAR request failed" });
    } finally {
      setDsarLoading(false);
    }
  }

  async function loadEvidence() {
    setEvidenceLoading(true);
    try {
      const [d, c] = await Promise.all([
        compliance.decisionEvidence(tenantId, 200),
        compliance.caseEvidence(tenantId, 200),
      ]);
      setDecisionEvidence(d as unknown as Record<string, unknown>);
      setCaseEvidence(c as unknown as Record<string, unknown>);
      const [dk, ck] = await Promise.all([compliance.decisionEvidenceKeys(), compliance.caseEvidenceKeys()]);
      setDecisionKeyId(dk.active_key_id);
      setCaseKeyId(ck.active_key_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Evidence export failed");
    } finally {
      setEvidenceLoading(false);
    }
  }

  function downloadJson(filename: string, data: unknown) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function verifyDecisionBundle() {
    if (!decisionEvidence) return;
    try {
      const res = await compliance.verifyDecisionEvidence(decisionEvidence);
      setDecisionVerify(res.valid ? `Verified (key ${res.active_key_id})` : "Verification failed");
    } catch (e) {
      setDecisionVerify(e instanceof Error ? e.message : "Verification failed");
    }
  }

  async function verifyCaseBundle() {
    if (!caseEvidence) return;
    try {
      const res = await compliance.verifyCaseEvidence(caseEvidence);
      setCaseVerify(res.valid ? `Verified (key ${res.active_key_id})` : "Verification failed");
    } catch (e) {
      setCaseVerify(e instanceof Error ? e.message : "Verification failed");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-brand-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-gray-400 text-sm">Loading compliance data...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="bg-red-900/30 border border-red-700 text-red-300 px-6 py-4 rounded-lg max-w-lg text-center">
          <p className="font-medium">Error</p>
          <p className="text-sm mt-1 text-red-400">{error}</p>
          <button
            className="mt-3 px-4 py-1.5 text-xs rounded bg-red-700 hover:bg-red-600 text-white transition-colors"
            onClick={() => { setError(null); setLoading(true); fetchRegions(); }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const regionKeys = Object.keys(regions);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header + Region Selector */}
      <div className="flex items-center justify-between">
        <div>
          <PageTitle module="compliance">Compliance</PageTitle>
          <p className="text-sm text-gray-400 mt-1">Privacy regulations, DSAR handling, and certification readiness</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-sm text-gray-400">Region:</label>
          <select
            value={selectedRegion}
            onChange={(e) => setSelectedRegion(e.target.value)}
            className="bg-surface-800 border border-surface-600 text-gray-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            {regionKeys.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Privacy Profile Card */}
      {profile && (
        <section className="bg-surface-800 border border-surface-700 rounded-xl p-6">
          <h2 className="text-lg font-semibold text-gray-100 mb-4 flex items-center gap-2">
            <span className="text-brand-400">&#x1F512;</span> Privacy Profile — {profile.regulation || selectedRegion}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {/* Key Rights */}
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-300 uppercase tracking-wider">Key Rights</h3>
              <div className="space-y-1">
                {Object.entries(profile.rights ?? {}).map(([right, enabled]) => (
                  <div key={right} className="flex items-center gap-2 text-sm">
                    <span className={enabled ? "text-emerald-400" : "text-gray-600"}>
                      {enabled ? "✓" : "✗"}
                    </span>
                    <span className={enabled ? "text-gray-200" : "text-gray-500"}>
                      {right.replace(/_/g, " ")}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Consent Requirements */}
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-300 uppercase tracking-wider">Consent Requirements</h3>
              <ul className="space-y-1 text-sm text-gray-300">
                {(profile.consent_requirements ?? []).map((req, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-brand-400 mt-0.5">•</span>
                    {req}
                  </li>
                ))}
              </ul>
            </div>

            {/* Retention Periods */}
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-300 uppercase tracking-wider">Retention Periods</h3>
              <div className="space-y-1">
                {Object.entries(profile.retention_periods ?? {}).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-sm">
                    <span className="text-gray-400">{k.replace(/_/g, " ")}</span>
                    <span className="text-gray-200 font-mono">{String(v)}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Encryption Requirements */}
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-300 uppercase tracking-wider">Encryption</h3>
              <ul className="space-y-1 text-sm text-gray-300">
                {(profile.encryption_requirements ?? []).map((req, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-brand-400 mt-0.5">•</span>
                    {req}
                  </li>
                ))}
              </ul>
            </div>

            {/* Cross-Border Rules */}
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-300 uppercase tracking-wider">Cross-Border Rules</h3>
              <ul className="space-y-1 text-sm text-gray-300">
                {(profile.cross_border_rules ?? []).map((rule, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-brand-400 mt-0.5">•</span>
                    {rule}
                  </li>
                ))}
              </ul>
            </div>

            {/* Breach Notification */}
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-300 uppercase tracking-wider">Breach Notification</h3>
              <p className="text-sm text-gray-200 bg-surface-700 rounded-lg px-3 py-2 font-mono">
                {profile.breach_notification_timeline || "N/A"}
              </p>
            </div>
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* DSAR Panel */}
        <section className="bg-surface-800 border border-surface-700 rounded-xl p-6">
          <h2 className="text-lg font-semibold text-gray-100 mb-4 flex items-center gap-2">
            <span className="text-brand-400">&#x1F4CB;</span> Data Subject Access Request
          </h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Entity ID</label>
              <input
                type="text"
                value={dsarEntityId}
                onChange={(e) => setDsarEntityId(e.target.value)}
                placeholder="e.g. user-12345"
                className="w-full bg-surface-900 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Request Type</label>
              <div className="flex gap-2">
                {(["access", "erasure", "portability"] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setDsarType(t)}
                    className={`px-4 py-2 text-sm rounded-lg border transition-colors capitalize ${
                      dsarType === t
                        ? "bg-brand-600/20 border-brand-500 text-brand-400"
                        : "bg-surface-900 border-surface-600 text-gray-400 hover:border-surface-500"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <button
              onClick={handleDsarSubmit}
              disabled={dsarLoading || !dsarEntityId.trim()}
              className="w-full px-4 py-2.5 text-sm font-medium rounded-lg bg-brand-600 hover:bg-brand-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {dsarLoading ? "Processing…" : "Submit Request"}
            </button>
            {dsarResult !== null && (
              <div className="mt-3 bg-surface-900 border border-surface-600 rounded-lg p-4 max-h-64 overflow-y-auto">
                <pre className="text-xs text-gray-300 whitespace-pre-wrap break-words font-mono">
                  {JSON.stringify(dsarResult, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </section>

        {/* ROPA */}
        <section className="bg-surface-800 border border-surface-700 rounded-xl p-6">
          <h2 className="text-lg font-semibold text-gray-100 mb-4 flex items-center gap-2">
            <span className="text-brand-400">&#x1F4D1;</span> Data Processing Record (ROPA)
          </h2>
          {ropa && ropa.length > 0 ? (
            <div className="space-y-4 max-h-[28rem] overflow-y-auto pr-1">
              {ropa.map((entry, i) => (
                <div key={i} className="bg-surface-900 border border-surface-700 rounded-lg p-4 space-y-2">
                  <h4 className="text-sm font-semibold text-gray-200">{entry.processing_purpose}</h4>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    <span className="text-gray-500">Legal Basis</span>
                    <span className="text-gray-300">{entry.legal_basis}</span>
                    <span className="text-gray-500">Retention</span>
                    <span className="text-gray-300">{entry.retention}</span>
                    <span className="text-gray-500">Categories</span>
                    <span className="text-gray-300">{(entry.data_categories ?? []).join(", ")}</span>
                    <span className="text-gray-500">Subjects</span>
                    <span className="text-gray-300">{(entry.data_subjects ?? []).join(", ")}</span>
                    <span className="text-gray-500">Recipients</span>
                    <span className="text-gray-300">{(entry.recipients ?? []).join(", ")}</span>
                    <span className="text-gray-500">Safeguards</span>
                    <span className="text-gray-300">{(entry.safeguards ?? []).join(", ")}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500 italic">No ROPA records available for this region.</p>
          )}
        </section>
      </div>

      {/* Certification Readiness */}
      {certifications && certifications.frameworks && (
        <section className="bg-surface-800 border border-surface-700 rounded-xl p-6">
          <h2 className="text-lg font-semibold text-gray-100 mb-5 flex items-center gap-2">
            <span className="text-brand-400">&#x2705;</span> Certification Readiness
          </h2>
          <div className="space-y-6">
            {certifications.frameworks.map((fw) => {
              const pct = frameworkProgress(fw.controls);
              return (
                <div key={fw.name}>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-semibold text-gray-200">{fw.name}</h3>
                    <span className="text-xs text-gray-400">{fw.controls.length} controls</span>
                  </div>

                  {/* Progress bar */}
                  <div className="w-full h-2.5 bg-surface-700 rounded-full overflow-hidden flex mb-3">
                    <div className="bg-emerald-500 h-full transition-all" style={{ width: `${pct.implemented}%` }} />
                    <div className="bg-yellow-500 h-full transition-all" style={{ width: `${pct.configurable}%` }} />
                    <div className="bg-orange-500 h-full transition-all" style={{ width: `${pct.partial}%` }} />
                  </div>

                  {/* Controls grid */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                    {fw.controls.map((ctrl) => (
                      <div
                        key={ctrl.id}
                        className="flex items-center justify-between bg-surface-900 border border-surface-700 rounded-lg px-3 py-2"
                      >
                        <div className="min-w-0">
                          <span className="text-xs font-mono text-gray-400 block">{ctrl.id}</span>
                          <span className="text-xs text-gray-300 block truncate">{ctrl.description}</span>
                        </div>
                        <span
                          className={`ml-2 flex-shrink-0 text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full border ${statusColor(ctrl.status)}`}
                        >
                          {ctrl.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Legend */}
          <div className="flex items-center gap-4 mt-5 pt-4 border-t border-surface-700">
            <div className="flex items-center gap-1.5 text-xs">
              <span className="w-3 h-3 rounded-full bg-emerald-500" />
              <span className="text-gray-400">Implemented</span>
            </div>
            <div className="flex items-center gap-1.5 text-xs">
              <span className="w-3 h-3 rounded-full bg-yellow-500" />
              <span className="text-gray-400">Configurable</span>
            </div>
            <div className="flex items-center gap-1.5 text-xs">
              <span className="w-3 h-3 rounded-full bg-orange-500" />
              <span className="text-gray-400">Partial</span>
            </div>
          </div>
        </section>
      )}

      {/* Trust Center Evidence */}
      <section className="bg-surface-800 border border-surface-700 rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-100 flex items-center gap-2">
            <span className="text-brand-400">🧾</span> Trust Center Evidence Exports
          </h2>
          <button
            onClick={loadEvidence}
            disabled={evidenceLoading}
            className="px-4 py-2 text-sm rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-white transition-colors"
          >
            {evidenceLoading ? "Loading..." : "Load Evidence"}
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="bg-surface-900 border border-surface-700 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-200">Decision Controls Evidence</h3>
              {decisionEvidence && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={verifyDecisionBundle}
                    className="text-xs px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-white"
                  >
                    Verify
                  </button>
                  <button
                    onClick={() => downloadJson(`decision-evidence-${tenantId}.json`, decisionEvidence)}
                    className="text-xs px-2 py-1 rounded bg-surface-700 hover:bg-surface-600 text-gray-200"
                  >
                    Download JSON
                  </button>
                </div>
              )}
            </div>
            <p className="text-[11px] text-gray-500 mb-1">Active Key ID: {decisionKeyId || "unknown"}</p>
            <p className="text-[11px] text-gray-500 mb-2">{integritySummary(decisionEvidence)}</p>
            {decisionVerify && <p className="text-[11px] text-emerald-400 mb-2">{decisionVerify}</p>}
            {decisionEvidence ? (
              <pre className="text-xs text-gray-400 max-h-64 overflow-y-auto whitespace-pre-wrap">
                {JSON.stringify(decisionEvidence, null, 2)}
              </pre>
            ) : (
              <p className="text-xs text-gray-500">No decision evidence loaded.</p>
            )}
          </div>

          <div className="bg-surface-900 border border-surface-700 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-200">Case Controls Evidence</h3>
              {caseEvidence && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={verifyCaseBundle}
                    className="text-xs px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-white"
                  >
                    Verify
                  </button>
                <button
                  onClick={() => downloadJson(`case-evidence-${tenantId}.json`, caseEvidence)}
                  className="text-xs px-2 py-1 rounded bg-surface-700 hover:bg-surface-600 text-gray-200"
                >
                  Download JSON
                </button>
                </div>
              )}
            </div>
            <p className="text-[11px] text-gray-500 mb-1">Active Key ID: {caseKeyId || "unknown"}</p>
            <p className="text-[11px] text-gray-500 mb-2">{integritySummary(caseEvidence)}</p>
            {caseVerify && <p className="text-[11px] text-emerald-400 mb-2">{caseVerify}</p>}
            {caseEvidence ? (
              <pre className="text-xs text-gray-400 max-h-64 overflow-y-auto whitespace-pre-wrap">
                {JSON.stringify(caseEvidence, null, 2)}
              </pre>
            ) : (
              <p className="text-xs text-gray-500">No case evidence loaded.</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
