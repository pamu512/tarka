import { useCallback, useState } from "react";
import { features } from "../api/client";
import { PageTitle } from "../components/PageTitle";

const DEFAULT_PAYLOAD = `{
  "amount": 100,
  "currency": "USD",
  "device_id": "dev-1",
  "ip_address": "198.51.100.2"
}`;

const DEFAULT_EXPECTED = `{
  "event_count_1h": 0
}`;

export default function FeatureTools() {
  const [tenantId, setTenantId] = useState("demo-tenant");
  const [entityId, setEntityId] = useState("demo-entity");
  const [payloadJson, setPayloadJson] = useState(DEFAULT_PAYLOAD);
  const [expectedJson, setExpectedJson] = useState(DEFAULT_EXPECTED);
  const [epsilon, setEpsilon] = useState("0.5");
  const [tab, setTab] = useState<"velocity" | "parity">("velocity");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runVelocity = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      let payload: Record<string, unknown> = {};
      try {
        payload = JSON.parse(payloadJson) as Record<string, unknown>;
      } catch {
        throw new Error("Payload must be valid JSON");
      }
      const data = await features.velocityQuery({ tenant_id: tenantId, entity_id: entityId, payload });
      setResult(JSON.stringify(data, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [tenantId, entityId, payloadJson]);

  const runParity = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      let payload: Record<string, unknown> = {};
      let expected: Record<string, number> = {};
      try {
        payload = JSON.parse(payloadJson) as Record<string, unknown>;
      } catch {
        throw new Error("Payload must be valid JSON");
      }
      try {
        const raw = JSON.parse(expectedJson) as Record<string, unknown>;
        expected = Object.fromEntries(
          Object.entries(raw).map(([k, v]) => [k, typeof v === "number" ? v : Number(v)]),
        );
      } catch {
        throw new Error("Expected counters must be valid JSON object of numbers");
      }
      const eps = parseFloat(epsilon);
      if (Number.isNaN(eps) || eps < 0) throw new Error("Epsilon must be a non-negative number");
      const data = await features.parityVerify({
        tenant_id: tenantId,
        entity_id: entityId,
        payload,
        expected,
        epsilon: eps,
      });
      setResult(JSON.stringify(data, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [tenantId, entityId, payloadJson, expectedJson, epsilon]);

  return (
    <div className="p-6 max-w-4xl space-y-6 animate-fade-in">
      <PageTitle module="compliance">Feature tools</PageTitle>
      <p className="text-sm text-gray-500 -mt-2">
        Live velocity counters and parity verification against the same Redis aggregate store as the Decision API (
        <code className="text-gray-600">POST /v1/velocity/query</code>, <code className="text-gray-600">POST /v1/internal/parity/verify</code>
        ). Requires feature-service with Redis — see <code className="text-gray-600">deploy/docker-compose.yml</code> (
        <code className="text-gray-600">--profile ml</code> or <code className="text-gray-600">full</code>). Optional{" "}
        <code className="text-gray-600">VITE_FEATURE_SERVICE_API_KEY</code> if the service uses <code className="text-gray-600">API_KEYS</code>.
      </p>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setTab("velocity")}
          className={`px-3 py-1.5 rounded-lg text-sm ${tab === "velocity" ? "bg-brand-600 text-white" : "bg-surface-800 text-gray-400"}`}
        >
          Velocity query
        </button>
        <button
          type="button"
          onClick={() => setTab("parity")}
          className={`px-3 py-1.5 rounded-lg text-sm ${tab === "parity" ? "bg-brand-600 text-white" : "bg-surface-800 text-gray-400"}`}
        >
          Parity verify
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-xs text-gray-500">
          Tenant ID
          <input
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            className="mt-1 w-full bg-surface-900 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200"
          />
        </label>
        <label className="block text-xs text-gray-500">
          Entity ID
          <input
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
            className="mt-1 w-full bg-surface-900 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200"
          />
        </label>
      </div>

      <label className="block text-xs text-gray-500">
        Payload JSON (same shape as evaluate payload for velocity keys)
        <textarea
          value={payloadJson}
          onChange={(e) => setPayloadJson(e.target.value)}
          rows={8}
          className="mt-1 w-full font-mono text-xs bg-surface-950 border border-surface-600 rounded-lg px-3 py-2 text-gray-200"
        />
      </label>

      {tab === "parity" && (
        <>
          <label className="block text-xs text-gray-500">
            Expected counters (map of key → number)
            <textarea
              value={expectedJson}
              onChange={(e) => setExpectedJson(e.target.value)}
              rows={5}
              className="mt-1 w-full font-mono text-xs bg-surface-950 border border-surface-600 rounded-lg px-3 py-2 text-gray-200"
            />
          </label>
          <label className="block text-xs text-gray-500">
            Epsilon
            <input
              value={epsilon}
              onChange={(e) => setEpsilon(e.target.value)}
              className="mt-1 w-32 bg-surface-900 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200"
            />
          </label>
        </>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={loading}
          onClick={() => void (tab === "velocity" ? runVelocity() : runParity())}
          className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium disabled:opacity-50"
        >
          {loading ? "Running…" : tab === "velocity" ? "Query velocity" : "Run parity verify"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300 whitespace-pre-wrap font-mono">
          {error}
        </div>
      )}
      {result && (
        <pre className="rounded-lg border border-surface-700 bg-surface-950 p-4 text-xs text-gray-300 overflow-x-auto">{result}</pre>
      )}
    </div>
  );
}
