import { useCallback, useEffect, useReducer, useState } from "react";
import { Link } from "react-router-dom";
import { cases, type SarTransportBoardCard, type SarTransportBoardResponse } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

const SYNC_COOLDOWN_MS = 60_000;

function KanbanColumn({
  title,
  subtitle,
  accentClass,
  column,
}: {
  title: string;
  subtitle: string;
  accentClass: string;
  column: { count: number; items: SarTransportBoardCard[] };
}) {
  return (
    <div className="flex min-h-[22rem] flex-col rounded-xl border border-surface-700 bg-surface-900/80 overflow-hidden">
      <div className={`border-b border-surface-700 px-3 py-2.5 ${accentClass}`}>
        <div className="text-sm font-semibold text-gray-100">{title}</div>
        <div className="text-[11px] text-gray-500 mt-0.5 leading-snug">{subtitle}</div>
        <div className="text-xs text-gray-400 mt-1 tabular-nums">{column.count} total</div>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-2 min-h-0">
        {column.items.length === 0 ? (
          <div className="text-xs text-gray-600 px-1 py-4 text-center">No intents in this column.</div>
        ) : (
          column.items.map((card) => (
            <div
              key={card.id}
              className="rounded-lg border border-surface-600/80 bg-surface-950/90 px-2.5 py-2 text-xs space-y-1"
            >
              <div className="font-mono text-[11px] text-gray-400 truncate" title={card.id}>
                {card.id.slice(0, 8)}…
              </div>
              <div className="text-gray-300">
                <span className="text-gray-500">status</span>{" "}
                <span className="font-medium text-brand-200/90">{card.status}</span>
              </div>
              <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-gray-500">
                <Link className="text-sky-400/90 hover:text-sky-300 underline-offset-2 hover:underline" to={`/cases/${card.case_id}`}>
                  Case
                </Link>
                {card.updated_at && <span className="tabular-nums">upd {new Date(card.updated_at).toLocaleString()}</span>}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function OpsSarTransportBoard() {
  const [tenantId, setTenantId] = useState("demo");
  const [board, setBoard] = useState<SarTransportBoardResponse | null>(null);
  const [boardErr, setBoardErr] = useState<string | null>(null);
  const [syncErr, setSyncErr] = useState<string | null>(null);
  const [syncInFlight, setSyncInFlight] = useState(false);
  const [nextSyncAllowedAt, setNextSyncAllowedAt] = useState(0);
  const [, bumpCooldownUi] = useReducer((n) => n + 1, 0);

  useEffect(() => {
    if (Date.now() >= nextSyncAllowedAt) return;
    const t = window.setInterval(() => bumpCooldownUi(), 500);
    return () => window.clearInterval(t);
  }, [nextSyncAllowedAt]);

  const loadBoard = useCallback(async () => {
    setBoardErr(null);
    try {
      const data = await cases.sarTransportBoard(tenantId.trim() || "demo");
      setBoard(data);
    } catch (e) {
      setBoardErr(toUserFacingError(e, { subject: "SAR transport board", action: "load filing intents from case-api" }));
    }
  }, [tenantId]);

  useEffect(() => {
    void loadBoard();
  }, [loadBoard]);

  useEffect(() => {
    const id = window.setInterval(() => void loadBoard(), 20_000);
    return () => window.clearInterval(id);
  }, [loadBoard]);

  const syncCooldownActive = Date.now() < nextSyncAllowedAt;
  const syncSecondsLeft = Math.max(0, Math.ceil((nextSyncAllowedAt - Date.now()) / 1000));

  const handleForceSync = async () => {
    if (syncInFlight || syncCooldownActive) return;
    setSyncErr(null);
    setSyncInFlight(true);
    try {
      await cases.forceSarTransportSftpSync();
      await loadBoard();
    } catch (e) {
      setSyncErr(toUserFacingError(e, { subject: "Force SFTP sync", action: "publish SAR transport tick / process queue" }));
    } finally {
      setSyncInFlight(false);
      setNextSyncAllowedAt(Date.now() + SYNC_COOLDOWN_MS);
    }
  };

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1 min-w-0">
          <PageTitle module="compliance">SAR worker monitoring</PageTitle>
          <p className="text-sm text-gray-500 max-w-2xl">
            Kanban view backed by <span className="font-mono text-gray-400">sar_filing_intents</span> (case-api).{" "}
            <span className="font-mono text-gray-400">Claimed</span> maps to <span className="font-mono">SFTP_QUEUED</span> — the
            worker does not persist a separate &quot;claimed&quot; row state.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:items-end shrink-0">
          <label className="text-xs text-gray-500 w-full sm:w-56">
            Tenant
            <input
              className="mt-0.5 w-full rounded-md border border-surface-600 bg-surface-950 px-2 py-1.5 text-sm text-gray-200"
              value={tenantId}
              onChange={(ev) => setTenantId(ev.target.value)}
              spellCheck={false}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded-lg border border-surface-600 bg-surface-800 px-3 py-1.5 text-sm text-gray-200 hover:bg-surface-800/90 disabled:opacity-40"
              onClick={() => void loadBoard()}
            >
              Refresh board
            </button>
            <button
              type="button"
              className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-sm text-amber-100 hover:bg-amber-500/25 disabled:opacity-40 disabled:cursor-not-allowed"
              disabled={syncInFlight || syncCooldownActive}
              title={
                syncCooldownActive
                  ? `Rate limited: next sync in ${syncSecondsLeft}s (client + server 60s)`
                  : "Publish transport tick and process up to one queued intent"
              }
              onClick={() => void handleForceSync()}
            >
              {syncInFlight ? "Syncing…" : syncCooldownActive ? `Force SFTP sync (${syncSecondsLeft}s)` : "Force SFTP sync"}
            </button>
          </div>
        </div>
      </div>

      {boardErr && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200/90 space-y-1">
          <p>{boardErr}</p>
          <SupportIdHint
            message={boardErr}
            className="flex flex-wrap items-center gap-2 text-[11px] text-amber-200/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-amber-400/35 hover:border-amber-300/50 hover:text-amber-100 transition-colors"
          />
        </div>
      )}

      {syncErr && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200/90 space-y-1">
          <p>{syncErr}</p>
          <SupportIdHint
            message={syncErr}
            className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
          />
        </div>
      )}

      {board && (
        <div className="grid gap-4 md:grid-cols-3">
          <KanbanColumn
            title="Pending"
            subtitle="DB: FILED or APPROVED — analyst-cleared, not yet on the SFTP queue."
            accentClass="bg-violet-500/10 border-violet-500/20"
            column={board.columns.pending}
          />
          <KanbanColumn
            title="Claimed"
            subtitle="DB: SFTP_QUEUED — worker pipeline / SFTP upload queue."
            accentClass="bg-sky-500/10 border-sky-500/20"
            column={board.columns.claimed}
          />
          <KanbanColumn
            title="Uploaded"
            subtitle="DB: TRANSMITTED or ACKNOWLEDGED."
            accentClass="bg-emerald-500/10 border-emerald-500/20"
            column={board.columns.uploaded}
          />
        </div>
      )}

      {board && board.failed.count > 0 && (
        <div className="rounded-xl border border-rose-500/25 bg-rose-500/5 p-4 space-y-2">
          <div className="text-sm font-semibold text-rose-200/90">Failed ({board.failed.count})</div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 max-h-48 overflow-y-auto">
            {board.failed.items.map((card) => (
              <div key={card.id} className="rounded-md border border-rose-500/20 bg-surface-950/80 px-2 py-1.5 text-[11px] font-mono text-gray-400 truncate">
                {card.id} ·{" "}
                <Link className="text-sky-400/90 hover:underline" to={`/cases/${card.case_id}`}>
                  case
                </Link>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
