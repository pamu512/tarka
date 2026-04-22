import { useState } from "react";
import { osint } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

interface OsintResult {
  composite_risk_score: number;
  risk_level: string;
  enrichments: Record<string, unknown>;
  signals_queried: number;
  elapsed_ms: number;
}

type EnrichmentSection = "ip" | "email" | "phone" | "domain" | "identity";

function riskColor(score: number): string {
  if (score < 30) return "#22c55e";
  if (score < 50) return "#eab308";
  if (score < 70) return "#f97316";
  return "#ef4444";
}

function riskBadgeClasses(level: string): string {
  switch (level.toLowerCase()) {
    case "low":
      return "bg-green-600/20 text-green-400 border-green-600/30";
    case "medium":
      return "bg-yellow-600/20 text-yellow-400 border-yellow-600/30";
    case "high":
      return "bg-orange-600/20 text-orange-400 border-orange-600/30";
    case "critical":
      return "bg-red-600/20 text-red-400 border-red-600/30";
    default:
      return "bg-gray-600/20 text-gray-400 border-gray-600/30";
  }
}

function RiskGauge({ score }: { score: number }) {
  const color = riskColor(score);
  const circumference = 2 * Math.PI * 54;
  const filled = (score / 100) * circumference;

  return (
    <div className="relative w-36 h-36 flex items-center justify-center">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r="54" fill="none" stroke="#1e293b" strokeWidth="10" />
        <circle
          cx="60"
          cy="60"
          r="54"
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - filled}
          strokeLinecap="round"
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="text-3xl font-bold" style={{ color }}>
          {score}
        </span>
        <span className="text-xs text-gray-500">/ 100</span>
      </div>
    </div>
  );
}

function DetailCard({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined) return null;
  const display =
    typeof value === "boolean" ? (value ? "Yes" : "No") : String(value);
  const isBoolTrue = typeof value === "boolean" && value;
  const isBoolFalse = typeof value === "boolean" && !value;

  return (
    <div className="flex justify-between items-center py-1.5 border-b border-surface-700/50 last:border-0">
      <span className="text-xs text-gray-400">{label}</span>
      <span
        className={`text-xs font-medium ${
          isBoolTrue
            ? "text-red-400"
            : isBoolFalse
            ? "text-green-400"
            : "text-gray-200"
        }`}
      >
        {display}
      </span>
    </div>
  );
}

function SourceCard({ name, data }: { name: string; data: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="bg-surface-800/50 rounded-lg border border-surface-700/50">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-surface-700/30 rounded-lg transition-colors"
      >
        <span className="text-xs font-medium text-gray-300">{name}</span>
        <span className="text-gray-500 text-xs">{open ? "\u25B2" : "\u25BC"}</span>
      </button>
      {open && (
        <div className="px-3 pb-2">
          {Object.entries(data).map(([k, v]) => (
            <DetailCard key={k} label={k} value={v} />
          ))}
        </div>
      )}
    </div>
  );
}

function IpSection({ data }: { data: Record<string, unknown> }) {
  const flags = data.flags as Record<string, boolean> | undefined;
  const geo = data.geo as Record<string, unknown> | undefined;
  const ports = data.open_ports as number[] | undefined;
  const vulns = data.vulnerabilities as unknown[] | undefined;
  const sources = data.sources as Record<string, unknown>[] | undefined;

  return (
    <div className="space-y-3">
      {data.aggregate_risk_score != null && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">Aggregate Risk:</span>
          <span className="text-sm font-bold" style={{ color: riskColor(Number(data.aggregate_risk_score)) }}>
            {String(data.aggregate_risk_score)}
          </span>
        </div>
      )}
      {flags && (
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(flags).map(([k, v]) => (
            <div
              key={k}
              className={`flex items-center gap-2 px-2 py-1 rounded text-xs ${
                v ? "bg-red-900/30 text-red-400" : "bg-green-900/20 text-green-500"
              }`}
            >
              <span>{v ? "\u26A0" : "\u2713"}</span>
              <span>{k.replace(/_/g, " ")}</span>
            </div>
          ))}
        </div>
      )}
      {geo && (
        <div className="bg-surface-800/50 rounded p-2 space-y-1">
          <div className="text-xs font-medium text-gray-400 mb-1">Geo</div>
          {Object.entries(geo).map(([k, v]) => (
            <DetailCard key={k} label={k} value={v} />
          ))}
        </div>
      )}
      {ports && ports.length > 0 && (
        <div>
          <div className="text-xs text-gray-400 mb-1">Open Ports</div>
          <div className="flex flex-wrap gap-1">
            {ports.map((p) => (
              <span key={p} className="bg-surface-700 text-gray-300 text-xs px-2 py-0.5 rounded">
                {p}
              </span>
            ))}
          </div>
        </div>
      )}
      {vulns && vulns.length > 0 && (
        <div>
          <div className="text-xs text-red-400 mb-1">Vulnerabilities ({vulns.length})</div>
          {vulns.map((v, i) => (
            <div key={i} className="text-xs text-gray-400 bg-red-900/10 rounded px-2 py-1 mb-1">
              {typeof v === "object" ? JSON.stringify(v) : String(v)}
            </div>
          ))}
        </div>
      )}
      {sources &&
        sources.map((s, i) => <SourceCard key={i} name={`Source ${i + 1}`} data={s as Record<string, unknown>} />)}
    </div>
  );
}

function EmailSection({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="space-y-3">
      {data.aggregate_risk_score != null && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">Aggregate Risk:</span>
          <span className="text-sm font-bold" style={{ color: riskColor(Number(data.aggregate_risk_score)) }}>
            {String(data.aggregate_risk_score)}
          </span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-4">
        <DetailCard label="Disposable" value={data.is_disposable} />
        <DetailCard label="Reputation" value={data.reputation} />
        <DetailCard label="Breach Count" value={data.breach_count} />
        <DetailCard label="Domain" value={data.domain} />
        <DetailCard label="Free Provider" value={data.is_free_provider} />
        <DetailCard label="Gravatar" value={data.gravatar_exists} />
      </div>
      {data.social_profiles != null && (
        <div>
          <div className="text-xs text-gray-400 mb-1">Social Profiles</div>
          <div className="flex flex-wrap gap-1">
            {(Array.isArray(data.social_profiles) ? data.social_profiles : Object.keys(data.social_profiles as object)).map(
              (p: unknown, i: number) => (
                <span key={i} className="bg-brand-600/20 text-brand-400 text-xs px-2 py-0.5 rounded">
                  {String(p)}
                </span>
              ),
            )}
          </div>
        </div>
      )}
      {data.sources != null &&
        (data.sources as Record<string, unknown>[]).map((s, i) => (
          <SourceCard key={i} name={`Source ${i + 1}`} data={s as Record<string, unknown>} />
        ))}
    </div>
  );
}

function PhoneSection({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="space-y-3">
      {data.aggregate_risk_score != null && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">Aggregate Risk:</span>
          <span className="text-sm font-bold" style={{ color: riskColor(Number(data.aggregate_risk_score)) }}>
            {String(data.aggregate_risk_score)}
          </span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-4">
        <DetailCard label="Carrier" value={data.carrier} />
        <DetailCard label="Line Type" value={data.line_type} />
        <DetailCard label="VOIP Detected" value={data.is_voip} />
        <DetailCard label="Country" value={data.country} />
        <DetailCard label="Country Code" value={data.country_code} />
        <DetailCard label="Valid" value={data.valid} />
      </div>
      {data.sources != null &&
        (data.sources as Record<string, unknown>[]).map((s, i) => (
          <SourceCard key={i} name={`Source ${i + 1}`} data={s as Record<string, unknown>} />
        ))}
    </div>
  );
}

function DomainSection({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="space-y-3">
      {data.aggregate_risk_score != null && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">Aggregate Risk:</span>
          <span className="text-sm font-bold" style={{ color: riskColor(Number(data.aggregate_risk_score)) }}>
            {String(data.aggregate_risk_score)}
          </span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-4">
        <DetailCard label="Age (days)" value={data.age_days} />
        <DetailCard label="Registration Date" value={data.registration_date} />
        <DetailCard label="Registrar" value={data.registrar} />
        <DetailCard label="Expiry" value={data.expiry_date} />
      </div>
      {data.nameservers != null && (
        <div>
          <div className="text-xs text-gray-400 mb-1">Nameservers</div>
          <div className="flex flex-wrap gap-1">
            {(data.nameservers as string[]).map((ns, i) => (
              <span key={i} className="bg-surface-700 text-gray-300 text-xs px-2 py-0.5 rounded">
                {ns}
              </span>
            ))}
          </div>
        </div>
      )}
      {data.sources != null &&
        (data.sources as Record<string, unknown>[]).map((s, i) => (
          <SourceCard key={i} name={`Source ${i + 1}`} data={s as Record<string, unknown>} />
        ))}
    </div>
  );
}

function IdentitySection({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="space-y-3">
      {data.aggregate_risk_score != null && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">Aggregate Risk:</span>
          <span className="text-sm font-bold" style={{ color: riskColor(Number(data.aggregate_risk_score)) }}>
            {String(data.aggregate_risk_score)}
          </span>
        </div>
      )}
      {data.social_profiles != null && (
        <div>
          <div className="text-xs text-gray-400 mb-1">Discovered Social Profiles</div>
          <div className="flex flex-wrap gap-1">
            {(Array.isArray(data.social_profiles) ? data.social_profiles : Object.keys(data.social_profiles as object)).map(
              (p: unknown, i: number) => (
                <span key={i} className="bg-brand-600/20 text-brand-400 text-xs px-2 py-0.5 rounded">
                  {String(p)}
                </span>
              ),
            )}
          </div>
        </div>
      )}
      {Object.entries(data)
        .filter(([k]) => k !== "social_profiles" && k !== "aggregate_risk_score" && k !== "sources")
        .map(([k, v]) => (
          <DetailCard key={k} label={k} value={v} />
        ))}
      {data.sources != null &&
        (data.sources as Record<string, unknown>[]).map((s, i) => (
          <SourceCard key={i} name={`Source ${i + 1}`} data={s as Record<string, unknown>} />
        ))}
    </div>
  );
}

const SECTION_CONFIG: Record<EnrichmentSection, { label: string; icon: string }> = {
  ip: { label: "IP Intelligence", icon: "\uD83C\uDF10" },
  email: { label: "Email Intelligence", icon: "\u2709" },
  phone: { label: "Phone Intelligence", icon: "\uD83D\uDCDE" },
  domain: { label: "Domain Intelligence", icon: "\uD83C\uDFE2" },
  identity: { label: "Identity Intelligence", icon: "\uD83D\uDC64" },
};

function EnrichmentPanel({ type, data }: { type: EnrichmentSection; data: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const config = SECTION_CONFIG[type];

  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-800/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-lg">{config.icon}</span>
          <span className="text-sm font-medium text-gray-200">{config.label}</span>
          {data.aggregate_risk_score != null && (
            <span
              className="text-xs font-bold px-2 py-0.5 rounded"
              style={{
                color: riskColor(Number(data.aggregate_risk_score)),
                backgroundColor: riskColor(Number(data.aggregate_risk_score)) + "1a",
              }}
            >
              {String(data.aggregate_risk_score)}
            </span>
          )}
        </div>
        <span className="text-gray-500 text-sm">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>
      {expanded && (
        <div className="px-4 pb-4 border-t border-surface-700">
          <div className="pt-3">
            {type === "ip" && <IpSection data={data} />}
            {type === "email" && <EmailSection data={data} />}
            {type === "phone" && <PhoneSection data={data} />}
            {type === "domain" && <DomainSection data={data} />}
            {type === "identity" && <IdentitySection data={data} />}
          </div>
        </div>
      )}
    </div>
  );
}

export default function OsintEnrichment() {
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [ip, setIp] = useState("");
  const [domain, setDomain] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OsintResult | null>(null);

  const canSubmit = !loading && (email || phone || ip || domain);

  const handleEnrich = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;

    setLoading(true);
    setError(null);
    setResult(null);

    const body: Record<string, string> = {};
    if (email.trim()) body.email = email.trim();
    if (phone.trim()) body.phone = phone.trim();
    if (ip.trim()) body.ip = ip.trim();
    if (domain.trim()) body.domain = domain.trim();

    try {
      const data = await osint.enrich(body);
      setResult(data);
    } catch (err) {
      setError(toUserFacingError(err, { subject: "OSINT enrichment", action: "run OSINT enrichment" }));
    } finally {
      setLoading(false);
    }
  };

  const enrichments = (result?.enrichments ?? {}) as Record<string, Record<string, unknown>>;
  const sectionOrder: EnrichmentSection[] = ["ip", "email", "phone", "domain", "identity"];
  const availableSections = sectionOrder.filter((s) => enrichments[s]);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <PageTitle module="osint">OSINT Enrichment</PageTitle>
        <p className="text-sm text-gray-500 mt-1">
          Investigate entities with open-source intelligence signals
        </p>
      </div>

      {/* Input Form */}
      <form
        onSubmit={handleEnrich}
        className="bg-surface-900 border border-surface-700 rounded-xl p-5"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Email</label>
            <input
              type="text"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
              className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/30"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Phone</label>
            <input
              type="text"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+1234567890"
              className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/30"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">IP Address</label>
            <input
              type="text"
              value={ip}
              onChange={(e) => setIp(e.target.value)}
              placeholder="1.2.3.4"
              className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/30"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Domain</label>
            <input
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="example.com"
              className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/30"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            type="submit"
            disabled={!canSubmit}
            className="px-5 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {loading ? "Enriching\u2026" : "Enrich"}
          </button>
        </div>
      </form>

      {error && (
        <div className="bg-red-900/20 border border-red-700/40 text-red-400 text-sm rounded-xl px-4 py-3 space-y-1">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-6">
          {/* Summary Row */}
          <div className="bg-surface-900 border border-surface-700 rounded-xl p-6">
            <div className="flex flex-wrap items-center gap-8">
              <div className="flex flex-col items-center">
                <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Composite Risk</div>
                <RiskGauge score={result.composite_risk_score} />
              </div>

              <div className="flex flex-col gap-3">
                <div>
                  <div className="text-xs text-gray-500 mb-1">Risk Level</div>
                  <span
                    className={`inline-block px-3 py-1 rounded-full text-xs font-semibold border uppercase tracking-wide ${riskBadgeClasses(
                      result.risk_level,
                    )}`}
                  >
                    {result.risk_level}
                  </span>
                </div>
                <div>
                  <div className="text-xs text-gray-500 mb-0.5">Sources Queried</div>
                  <div className="text-lg font-semibold text-gray-200">{result.signals_queried}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-500 mb-0.5">Time Taken</div>
                  <div className="text-lg font-semibold text-gray-200">{result.elapsed_ms} ms</div>
                </div>
              </div>
            </div>
          </div>

          {/* Enrichment Sections */}
          {availableSections.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
                Enrichment Details
              </h2>
              {availableSections.map((section) => (
                <EnrichmentPanel key={section} type={section} data={enrichments[section]} />
              ))}
            </div>
          )}

          {/* Raw fallback for unknown enrichment types */}
          {Object.keys(enrichments)
            .filter((k) => !sectionOrder.includes(k as EnrichmentSection))
            .map((key) => (
              <div key={key} className="bg-surface-900 border border-surface-700 rounded-xl p-4">
                <h3 className="text-sm font-medium text-gray-300 mb-2 capitalize">{key}</h3>
                <pre className="text-xs text-gray-400 overflow-x-auto whitespace-pre-wrap">
                  {JSON.stringify(enrichments[key], null, 2)}
                </pre>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
