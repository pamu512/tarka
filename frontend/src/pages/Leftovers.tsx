import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { Link } from "react-router";

import { cases, type LeftoverRow } from "../api/client";
import { FirstHourHint } from "../components/FirstHourHint";
import { PageTitle } from "../components/PageTitle";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { leftoverHuntSearch } from "../utils/leftoverVisualQuery";
import { toUserFacingError } from "../utils/userFacingErrors";

export default function Leftovers() {
  const { tenantId } = useTenantEnvironment();
  const navigate = useNavigate();
  const [rows, setRows] = useState<LeftoverRow[]>([]);
  const [err, setErr] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setErr("");
    cases
      .listLeftovers(tenantId || "demo")
      .then((r) => {
        if (!cancelled) setRows(r.leftovers || []);
      })
      .catch((e) => {
        if (!cancelled) setErr(toUserFacingError(e, { subject: "Leftovers", action: "load the leftover list" }));
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  async function workRow(row: LeftoverRow) {
    if (row.claimed_by) return;
    setBusyId(row.case_id);
    setErr("");
    try {
      await cases.claimLeftover(row.case_id, tenantId || "demo");
      navigate(`/graph?${leftoverHuntSearch({ ...row, tenant_id: tenantId || "demo" })}`);
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Leftover", action: "claim this leftover" }));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 space-y-4">
      <PageTitle module="cases">Leftovers</PageTitle>
      <FirstHourHint
        job="REVIEW and DENY land here. ALLOW never does. Open a row to Hunt that person; the receipt is why the pack fired."
        nextTo="/decisions"
        nextLabel="Receipts"
      />
      <p className="text-sm text-gray-500">Work arrives here. Work happens on Hunt.</p>
      {err ? (
        <p className="text-sm text-rose-300" role="alert">
          {err} Leftover Hold is unavailable — do not treat an empty table as “no work.”
        </p>
      ) : (
      <div className="overflow-x-auto rounded-lg border border-surface-700">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface-900 text-[11px] uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-3 py-2 font-medium">Entity</th>
              <th className="px-3 py-2 font-medium">Origin</th>
              <th className="px-3 py-2 font-medium">Outcome</th>
              <th className="px-3 py-2 font-medium">Pack / hits</th>
              <th className="px-3 py-2 font-medium">Brief</th>
              <th className="px-3 py-2 font-medium">Receipt</th>
              <th className="px-3 py-2 font-medium">Last act</th>
              <th className="px-3 py-2 font-medium">Claimed</th>
              <th className="px-3 py-2 font-medium">SLA</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-gray-500">
                  No leftovers. A REVIEW or DENY from evaluate (or make demo) mints one. ALLOW never does.
                </td>
              </tr>
            ) : null}
            {rows.map((row) => {
              const taken = Boolean(row.claimed_by);
              return (
                <tr key={row.case_id} className="border-t border-surface-800">
                  <td className="px-3 py-2 font-mono text-gray-200">
                    {taken ? (
                      row.entity_id
                    ) : (
                      <button
                        type="button"
                        disabled={busyId === row.case_id}
                        aria-label={`Work ${row.entity_id}`}
                        onClick={() => void workRow(row)}
                        className="text-brand-300 hover:underline disabled:opacity-50"
                      >
                        {row.entity_id}
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 text-gray-400">{row.origin}</td>
                  <td className="px-3 py-2 text-gray-400">{row.last_outcome ?? "—"}</td>
                  <td className="px-3 py-2 font-mono text-gray-400">
                    {row.pack_id || row.rule_hits?.length
                      ? `${row.pack_id || "—"} ${row.rule_hits?.length ? row.rule_hits.join(", ") : ""}`.trim()
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-gray-400" data-testid="leftover-brief">
                    {row.brief || "—"}
                  </td>
                  <td className="px-3 py-2">
                    {row.trace_id ? (
                      <Link
                        to={`/decisions/${encodeURIComponent(row.trace_id)}`}
                        className="text-brand-300 hover:underline"
                      >
                        receipt
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2 text-gray-400">{row.last_act ?? "—"}</td>
                  <td className="px-3 py-2 text-gray-400">{row.claimed_by ?? "free"}</td>
                  <td className="px-3 py-2 text-gray-400">{row.sla_breached ? "breached" : "ok"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      )}
    </div>
  );
}
