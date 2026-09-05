import { useEffect, useState } from "react";
import { Link } from "react-router";

import { decisions } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

type Row = {
  id: string;
  type: string;
  title: string;
  body: string;
  href: string;
  created_at: string;
  read_at: string | null;
};

export default function Notifications() {
  const { tenantId } = useTenantEnvironment();
  const [rows, setRows] = useState<Row[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    decisions
      .listObserveNotify(tenantId || "demo")
      .then((r) => {
        if (!cancelled) setRows(r.notifications || []);
      })
      .catch((e) => {
        if (!cancelled) setErr(toUserFacingError(e, { subject: "Notifications", action: "load observe events" }));
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  async function mark(row: Row) {
    try {
      await decisions.markObserveNotifyRead(tenantId || "demo", row.id);
      setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, read_at: r.read_at || new Date().toISOString() } : r)));
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Notifications", action: "mark read" }));
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8 space-y-4">
      <PageTitle module="notifications">Notifications</PageTitle>
      <p className="text-sm text-gray-500">
        Observe events only: ready to Promote, or a live rule slipped. This is not leftovers. A click does not Promote or demote.
      </p>
      {err ? (
        <p className="text-sm text-rose-300" role="alert">
          {err}
        </p>
      ) : null}
      <ul className="space-y-2">
        {rows.length === 0 && !err ? (
          <li className="text-sm text-gray-500">No Observe events yet.</li>
        ) : null}
        {rows.map((row) => (
          <li
            key={row.id}
            className="rounded-md border border-surface-700 bg-surface-900/70 px-3 py-2 text-sm"
            data-testid="observe-notify-row"
          >
            <p className="font-medium text-gray-100">{row.title}</p>
            <p className="text-gray-400 mt-1">{row.body}</p>
            <div className="mt-2 flex gap-3 text-xs">
              <Link to={row.href || "/ops/shadow"} className="text-brand-300 hover:underline">
                Open draft
              </Link>
              {!row.read_at ? (
                <button type="button" className="text-gray-400 hover:text-gray-200" onClick={() => void mark(row)}>
                  Mark read
                </button>
              ) : (
                <span className="text-gray-600">Read</span>
              )}
              <span className="text-gray-600 ml-auto">{row.created_at}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
