import { useCallback, useEffect, useState } from "react";

import { getAccessToken } from "@/api/authSession";
import { fields, toUserFacingApiError, type DiscoverOut, type FieldMapRow, type FieldRow } from "@/api/client";
import { DESK_PROFILE } from "@/config/leanNav";
import { decodeJwtPayload, extractRolesFromClaims } from "@/security/jwtClaims";
import { TarkaRbacRole } from "@/security/rbacConstants";

function jwtHasRiskArchitect(): boolean {
  const token = getAccessToken();
  if (!token) return false;
  const claims = decodeJwtPayload(token);
  if (!claims) return false;
  return extractRolesFromClaims(claims).includes(TarkaRbacRole.RiskArchitect);
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function FieldMapPanel({ tenantId }: { tenantId: string }) {
  const [rows, setRows] = useState<FieldRow[]>([]);
  const [maps, setMaps] = useState<FieldMapRow[]>([]);
  const [payloadText, setPayloadText] = useState("{\n  \n}");
  const [discovered, setDiscovered] = useState<DiscoverOut | null>(null);
  const [explanations, setExplanations] = useState<Record<string, string>>({});
  const [mapTo, setMapTo] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [listRows, mapRows] = await Promise.all([fields.list(tenantId), fields.maps(tenantId)]);
    setRows(listRows);
    setMaps(mapRows);
  }, [tenantId]);

  useEffect(() => {
    if (DESK_PROFILE !== "product" || !jwtHasRiskArchitect()) return;
    let cancelled = false;
    void load()
      .then(() => {
        if (!cancelled) setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(toUserFacingApiError(e, { subject: "Field registry", action: "load fields" }));
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  if (DESK_PROFILE !== "product" || !jwtHasRiskArchitect()) return null;

  async function handleDiscover() {
    setError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(payloadText);
    } catch {
      setError("Payload must be JSON.");
      return;
    }
    if (!isPlainRecord(parsed)) {
      setError("Payload must be a JSON object.");
      return;
    }
    setBusy(true);
    try {
      setDiscovered(await fields.discover({ tenant_id: tenantId, payload: parsed }));
    } catch (e) {
      setError(toUserFacingApiError(e, { subject: "Field registry", action: "discover payload keys" }));
    } finally {
      setBusy(false);
    }
  }

  async function handleApply(buyerKey: string) {
    const existing = mapTo[buyerKey]?.trim();
    setBusy(true);
    setError(null);
    try {
      if (existing) {
        await fields.putMap({ tenant_id: tenantId, buyer_key: buyerKey, registry_name: existing });
      } else {
        await fields.upsert(tenantId, buyerKey, {
          explanation: explanations[buyerKey] ?? "",
          source: "new_feature",
        });
      }
      await load();
    } catch (e) {
      setError(toUserFacingApiError(e, { subject: "Field registry", action: "save field map" }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      data-testid="field-map-panel"
      className="border border-surface-700 rounded-lg p-3 bg-surface-900/60 space-y-3 text-gray-300"
    >
      <div className="text-[10px] uppercase tracking-wide text-gray-500">Field map</div>
      {error && <p className="text-xs text-red-400">{error}</p>}
      <ul className="flex flex-wrap gap-1">
        {rows.map((row) => (
          <li key={row.name} className="flex items-baseline gap-1.5 text-[11px]">
            <code className="px-1.5 py-0.5 bg-surface-800 rounded text-gray-300">{row.name}</code>
            <span className="text-gray-500">{row.source}</span>
            <span className="text-gray-400">{row.explanation}</span>
          </li>
        ))}
      </ul>
      {maps.length > 0 && (
        <ul className="space-y-0.5 font-mono text-[11px] text-gray-400">
          {maps.map((m) => (
            <li key={`${m.tenant_id}:${m.buyer_key}`}>
              {m.buyer_key} → {m.registry_name}
            </li>
          ))}
        </ul>
      )}
      <textarea
        data-testid="field-map-payload"
        value={payloadText}
        onChange={(e) => setPayloadText(e.target.value)}
        rows={5}
        spellCheck={false}
        className="w-full bg-surface-800 border border-surface-600 text-gray-300 text-xs font-mono rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />
      <button
        type="button"
        onClick={() => void handleDiscover()}
        disabled={busy}
        className="px-2 py-1 rounded border border-surface-600 hover:bg-surface-800 text-gray-300 disabled:opacity-50"
      >
        Discover
      </button>
      {discovered?.candidates.map((c) => (
        <div key={c.buyer_key} className="flex flex-wrap items-center gap-2">
          <code className="text-[11px] text-gray-200">{c.buyer_key}</code>
          <input
            data-testid={`field-map-explanation-${c.buyer_key}`}
            value={explanations[c.buyer_key] ?? ""}
            onChange={(e) => setExplanations((prev) => ({ ...prev, [c.buyer_key]: e.target.value }))}
            placeholder="explanation"
            className="bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs text-gray-200 min-w-[10rem] flex-1"
          />
          <input
            data-testid={`field-map-map-to-${c.buyer_key}`}
            value={mapTo[c.buyer_key] ?? ""}
            onChange={(e) => setMapTo((prev) => ({ ...prev, [c.buyer_key]: e.target.value }))}
            placeholder="map to existing name"
            className="bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs font-mono text-gray-200 min-w-[8rem]"
          />
          <button
            type="button"
            data-testid={`field-map-apply-${c.buyer_key}`}
            onClick={() => void handleApply(c.buyer_key)}
            disabled={busy}
            className="px-2 py-1 rounded bg-brand-700 hover:bg-brand-600 disabled:opacity-50 text-white text-xs"
          >
            Apply
          </button>
        </div>
      ))}
    </section>
  );
}
