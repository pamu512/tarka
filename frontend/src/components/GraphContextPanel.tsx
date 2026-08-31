import { useCallback, useEffect, useId, useState } from "react";

import {
  cases,
  decisions,
  graph,
  type AuditEntry,
  type GraphEdge,
  type GraphEntityDeepContext,
  type GraphNode,
  type GraphObjectAttention,
} from "../api/client";
import { PackWhyStrip } from "./CaseView/PackWhyStrip";
import { DeviceIntegrityStrip } from "./CaseView/DeviceIntegrityStrip";
import { graphLaggedEvaluate, lastOutcomeLabel, rankRelatedLinks } from "../domain/graphInvestigation";
import { DISPOSITION_REASON_CODES } from "../config/dispositionReasonCodes";
import { DEVICE_CLUSTER_GRAPH_LABEL } from "../utils/entityDeviceClustering";
import { resolveIntegrityPresence } from "../utils/deviceIntegrity";
import { PACK_WHY_MISSING, resolvePackWhy } from "../utils/packWhy";
import { toUserFacingError } from "../utils/userFacingErrors";

type LoadState = "idle" | "loading" | "ready" | "not_found" | "error" | "cluster";

function GraphContextPanelSkeleton() {
  return (
    <div className="space-y-4 animate-pulse" aria-busy="true" aria-label="Loading entity context">
      <div className="h-4 bg-surface-700 rounded w-2/3" />
      <div className="h-3 bg-surface-800 rounded w-full" />
      <div className="h-3 bg-surface-800 rounded w-5/6" />
      <div className="space-y-2 pt-2">
        <div className="h-3 bg-surface-800 rounded w-1/3" />
        <div className="h-20 bg-surface-800/80 rounded-lg border border-surface-700/50" />
        <div className="h-20 bg-surface-800/80 rounded-lg border border-surface-700/50" />
      </div>
      <div className="space-y-2 pt-2">
        <div className="h-3 bg-surface-800 rounded w-1/4" />
        <div className="h-16 bg-surface-800/80 rounded-lg border border-surface-700/50" />
      </div>
      <div className="space-y-2 pt-2">
        <div className="h-3 bg-surface-800 rounded w-1/3" />
        <div className="h-14 bg-surface-800/80 rounded-lg border border-surface-700/50" />
      </div>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const RECEIPT_CAP = 8;

function isPackFiredDecision(decision: string | null | undefined): boolean {
  const d = String(decision || "").trim().toLowerCase();
  return d === "review" || d === "deny" || d === "flag";
}

function receiptTraceIds(hist: { last_trace_id?: string | null; trace_ids: string[] } | null): string[] {
  if (!hist) return [];
  const ids = [...(hist.trace_ids || [])];
  const last = String(hist.last_trace_id || "").trim();
  if (last && !ids.includes(last)) ids.push(last);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of ids) {
    const id = String(raw || "").trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out.slice(-RECEIPT_CAP);
}

async function loadMinimalReceipts(tenantId: string, traceIds: string[]): Promise<AuditEntry[]> {
  // ponytail: minimal has pack-why; analyst 403s this desk. Cap 8; one GET per id.
  const rows = await Promise.all(
    traceIds.map(async (tid) => {
      try {
        return await decisions.getAudit(tid, tenantId, { detail_level: "minimal" });
      } catch {
        return null;
      }
    }),
  );
  return rows.filter((r): r is AuditEntry => r != null);
}

type StoryHold = { outcome: string; created_at: string };
type StoryRow =
  | { kind: "evaluate"; at: string; receipt: AuditEntry }
  | { kind: "hold"; at: string; outcome: string }
  | { kind: "hop"; at: string; id: string; outcome: string };

function hopStoryFromLinks(
  seedId: string,
  edges: GraphEdge[],
  nodes: GraphNode[],
): StoryRow[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const rows: StoryRow[] = [];
  const seen = new Set<string>();
  for (const edge of edges) {
    if (edge.type !== "RESULTED_IN") continue;
    const other = edge.from_id === seedId ? edge.to_id : edge.to_id === seedId ? edge.from_id : "";
    if (!other || seen.has(other)) continue;
    const node = byId.get(other);
    if (!node?.labels?.includes("Decision")) continue;
    seen.add(other);
    const props = node.properties || {};
    rows.push({
      kind: "hop",
      id: other,
      at: String(props.created_at || ""),
      outcome: String(props.outcome || ""),
    });
  }
  return rows.sort((a, b) => b.at.localeCompare(a.at));
}

function holdForStory(
  lastAct: unknown,
  disposition: { outcome?: string; created_at?: string } | null,
): StoryHold | null {
  const fromAct = String(lastAct || "").trim();
  const fromDisp = String(disposition?.outcome || "").trim();
  const outcome = fromDisp || fromAct;
  if (!outcome) return null;
  return { outcome, created_at: String(disposition?.created_at || "").trim() };
}

function buildObjectStory(
  receipts: AuditEntry[],
  hold: StoryHold | null,
  hops: StoryRow[] = [],
): StoryRow[] {
  if (hops.length) {
    const rows = [...hops];
    if (hold && !rows.some((row) => row.kind === "hop" && row.outcome === hold.outcome)) {
      rows.push({ kind: "hold", at: hold.created_at, outcome: hold.outcome });
    }
    return rows.sort((a, b) => {
      if (a.kind === "hold" && !a.at) return -1;
      if (b.kind === "hold" && !b.at) return 1;
      return b.at.localeCompare(a.at);
    });
  }
  const rows: StoryRow[] = receipts.map((receipt) => ({
    kind: "evaluate" as const,
    at: String(receipt.created_at || ""),
    receipt,
  }));
  if (hold) {
    rows.push({ kind: "hold", at: hold.created_at, outcome: hold.outcome });
  }
  // Newest first. Untimed hold (last_act, no disposition clock) stays current-state at top.
  return rows.sort((a, b) => {
    if (a.kind === "hold" && !a.at) return -1;
    if (b.kind === "hold" && !b.at) return 1;
    return b.at.localeCompare(a.at);
  });
}

export type GraphContextPanelProps = {
  open: boolean;
  onClose: () => void;
  tenantId: string;
  entityId: string | null;
  /** Optional subgraph node for header chips while loading. */
  nodeHint?: GraphNode | null;
  /** In-column dossier (investigation workspace); skip the slide-over overlay. */
  embedded?: boolean;
  /** Re-seed Hunt on a linked object. */
  onSelectEntity?: (entityId: string) => void;
};

/**
 * Slide-over panel: loads ``graph.entityDeepContext`` when opened for a node.
 * Shows skeleton while loading; 404 is surfaced as a calm empty state (no stack traces).
 */
export function GraphContextPanel({
  open,
  onClose,
  tenantId,
  entityId,
  nodeHint,
  embedded,
  onSelectEntity,
}: GraphContextPanelProps) {
  const titleId = useId();
  const [state, setState] = useState<LoadState>("idle");
  const [data, setData] = useState<GraphEntityDeepContext | null>(null);
  const [objectNode, setObjectNode] = useState<GraphNode | null>(null);
  const [links, setLinks] = useState<{
    edges: GraphEdge[];
    nodes?: GraphNode[];
    attention?: GraphObjectAttention[];
  } | null>(null);
  const [history, setHistory] = useState<{
    last_trace_id?: string | null;
    trace_ids: string[];
    decisions?: Array<{
      id: string;
      outcome?: string | null;
      source?: string | null;
      kind?: string | null;
      trace_id?: string | null;
      created_at?: string | null;
    }>;
    properties?: Record<string, unknown>;
  } | null>(null);
  const [receipts, setReceipts] = useState<AuditEntry[]>([]);
  const [hold, setHold] = useState<StoryHold | null>(null);
  const [errMsg, setErrMsg] = useState("");
  const [actBusy, setActBusy] = useState(false);
  const [actMsg, setActMsg] = useState("");
  const [latestEval, setLatestEval] = useState<{ trace_id?: string | null } | null>(null);
  const [reasonCode, setReasonCode] = useState<(typeof DISPOSITION_REASON_CODES)[number]["code"]>(
    "FALSE_POSITIVE",
  );

  useEffect(() => {
    if (!open) {
      setState("idle");
      setData(null);
      setObjectNode(null);
      setLinks(null);
      setHistory(null);
      setReceipts([]);
      setHold(null);
      setLatestEval(null);
      setErrMsg("");
      setActMsg("");
    }
  }, [open]);

  const loadObject = useCallback(async () => {
    if (!entityId || !tenantId) return;
    const [obj, linkRow, hist, ctx, disposition, latest] = await Promise.all([
      graph.getEntity(entityId, tenantId),
      graph.entityLinks(entityId, tenantId),
      graph.entityHistory(entityId, tenantId),
      graph.entityDeepContext(entityId, tenantId),
      graph.latestDisposition(entityId, tenantId),
      graph.latestEvaluate(entityId, tenantId),
    ]);
    if (!obj && !linkRow && !hist && !ctx) {
      setState("not_found");
      return;
    }
    setObjectNode(obj);
    setLinks(linkRow);
    setHistory(hist);
    setData(ctx);
    const hops = hopStoryFromLinks(entityId, linkRow?.edges || [], linkRow?.nodes || []);
    setReceipts(hops.length ? [] : await loadMinimalReceipts(tenantId, receiptTraceIds(hist)));
    setHold(holdForStory(obj?.properties?.last_act ?? hist?.properties?.last_act, disposition));
    setLatestEval(latest);
    setState("ready");
  }, [entityId, tenantId]);

  useEffect(() => {
    if (!open || !entityId || !tenantId) return;
    const isCluster = Boolean(nodeHint?.labels?.includes(DEVICE_CLUSTER_GRAPH_LABEL));
    if (isCluster) {
      setState("cluster");
      setData(null);
      setErrMsg("");
      return;
    }
    let cancelled = false;
    setState("loading");
    setData(null);
    setObjectNode(null);
    setLinks(null);
    setHistory(null);
    setReceipts([]);
    setHold(null);
    setErrMsg("");
    void (async () => {
      try {
        await loadObject();
      } catch (e) {
        if (cancelled) return;
        setErrMsg(toUserFacingError(e, { subject: "Object", action: "load object context" }));
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, entityId, tenantId, nodeHint?.labels, loadObject]);

  const isPerson = Boolean(
    objectNode?.labels?.includes("Person") || nodeHint?.labels?.includes("Person"),
  );

  async function holdPerson() {
    if (!entityId || !tenantId || actBusy) return;
    setActBusy(true);
    setActMsg("");
    try {
      const row = await cases.actOnEntity({ tenant_id: tenantId, entity_id: entityId, action: "hold" });
      setActMsg(row.outcome === "held" ? "Held." : String(row.outcome || "Held."));
      await loadObject();
    } catch (e) {
      setActMsg(toUserFacingError(e, { subject: "Hold", action: "hold this person" }));
    } finally {
      setActBusy(false);
    }
  }

  async function releasePerson() {
    if (!entityId || !tenantId || actBusy) return;
    setActBusy(true);
    setActMsg("");
    try {
      const row = await cases.actOnEntity({ tenant_id: tenantId, entity_id: entityId, action: "release" });
      setActMsg(row.outcome === "released" ? "Released." : String(row.outcome || "Released."));
      await loadObject();
    } catch (e) {
      setActMsg(toUserFacingError(e, { subject: "Release", action: "release this person" }));
    } finally {
      setActBusy(false);
    }
  }

  async function resolvePerson() {
    if (!entityId || !tenantId || actBusy) return;
    setActBusy(true);
    setActMsg("");
    try {
      const row = await cases.actOnEntity({
        tenant_id: tenantId,
        entity_id: entityId,
        action: "resolve",
        reason_code: reasonCode,
      });
      setActMsg(row.outcome === "resolved" ? "Resolved." : String(row.outcome || "Resolved."));
      await loadObject();
    } catch (e) {
      setActMsg(toUserFacingError(e, { subject: "Resolve", action: "resolve this leftover" }));
    } finally {
      setActBusy(false);
    }
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !entityId) {
    if (embedded) {
      return (
        <div className="h-full flex items-center justify-center px-3 text-xs text-gray-500 text-center">
          Select a node on the canvas
        </div>
      );
    }
    return null;
  }

  const shell = (
      <aside
        role={embedded ? "region" : "dialog"}
        aria-modal={embedded ? undefined : true}
        aria-labelledby={titleId}
        className={
          embedded
            ? "relative h-full w-full flex flex-col bg-surface-950"
            : "relative h-full w-full max-w-md border-l border-surface-700 bg-surface-950 shadow-2xl flex flex-col transition-transform duration-200"
        }
      >
        <header className="shrink-0 border-b border-surface-800 px-4 py-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id={titleId} className="text-sm font-semibold text-gray-100 truncate">
              {state === "cluster"
                ? "Shared device cluster"
                : objectNode?.labels?.[0] || nodeHint?.labels?.[0] || "Object"}
            </h2>
            <p className="text-xs text-gray-500 font-mono truncate mt-0.5" title={entityId}>
              {entityId}
            </p>
            <p className="text-[11px] text-gray-400 mt-1" data-testid="last-outcome">
              {lastOutcomeLabel(objectNode ?? nodeHint)}
            </p>
            {graphLaggedEvaluate(latestEval, history) ? (
              <p className="text-[11px] text-amber-200/90 mt-1" role="status">
                Graph lagged this evaluate. Receipt is source of truth.
              </p>
            ) : null}
            {nodeHint?.labels?.length ? (
              <p className="text-[11px] text-gray-500 mt-1">
                Graph labels:{" "}
                <span className="text-gray-400">{nodeHint.labels.join(", ")}</span>
              </p>
            ) : null}
            {isPerson && state === "ready" ? (
              <div className="mt-2 space-y-1">
                <div className="flex flex-wrap gap-1">
                  <button
                    type="button"
                    disabled={actBusy}
                    onClick={() => void holdPerson()}
                    className="px-2 py-1 text-[11px] font-medium rounded-lg bg-amber-800/80 hover:bg-amber-700 disabled:opacity-50 text-amber-50"
                  >
                    Hold this person
                  </button>
                  <button
                    type="button"
                    disabled={actBusy}
                    onClick={() => void releasePerson()}
                    className="px-2 py-1 text-[11px] font-medium rounded-lg bg-surface-700 hover:bg-surface-600 disabled:opacity-50 text-gray-100"
                  >
                    Release
                  </button>
                </div>
                <div className="flex flex-wrap gap-1 items-center">
                  <label className="sr-only" htmlFor="leftover-reason">
                    Resolve reason
                  </label>
                  <select
                    id="leftover-reason"
                    value={reasonCode}
                    disabled={actBusy}
                    onChange={(e) =>
                      setReasonCode(e.target.value as (typeof DISPOSITION_REASON_CODES)[number]["code"])
                    }
                    className="bg-surface-800 border border-surface-600 text-[11px] text-gray-200 rounded px-1 py-1"
                  >
                    {DISPOSITION_REASON_CODES.map((r) => (
                      <option key={r.code} value={r.code}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    disabled={actBusy}
                    onClick={() => void resolvePerson()}
                    className="px-2 py-1 text-[11px] font-medium rounded-lg bg-sky-800/80 hover:bg-sky-700 disabled:opacity-50 text-sky-50"
                  >
                    Resolve
                  </button>
                </div>
                {actMsg ? <p className="text-[11px] text-gray-400">{actMsg}</p> : null}
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 text-gray-500 hover:text-gray-200 text-sm px-2 py-1 rounded border border-transparent hover:border-surface-600"
          >
            Close
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
          {state === "loading" ? <GraphContextPanelSkeleton /> : null}

          {state === "cluster" && nodeHint ? (
            <div className="rounded-lg border border-violet-500/35 bg-violet-950/25 px-4 py-4 text-sm text-gray-300 space-y-4">
              <p className="text-xs text-gray-500">
                Vertices merged by identical <span className="font-mono text-gray-400">device_hash</span> to surface
                coordinated activity (for example botnets or device farms).
              </p>
              <dl className="space-y-2 text-xs">
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-500 shrink-0">Members</dt>
                  <dd className="text-gray-200 font-mono text-right break-all">
                    {typeof nodeHint.properties?.cluster_member_count === "number"
                      ? String(nodeHint.properties.cluster_member_count)
                      : "—"}
                  </dd>
                </div>
                <div className="flex flex-col gap-1">
                  <dt className="text-gray-500">device_hash</dt>
                  <dd className="font-mono text-[11px] text-violet-200/90 break-all">
                    {typeof nodeHint.properties?.device_hash === "string"
                      ? nodeHint.properties.device_hash
                      : typeof nodeHint.properties?.cluster_member_ids === "string"
                        ? "(see vertex ids below)"
                        : "—"}
                  </dd>
                </div>
              </dl>
              {typeof nodeHint.properties?.cluster_member_ids === "string" &&
              nodeHint.properties.cluster_member_ids.trim() !== "" ? (
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-2">
                    Vertex ids in cluster
                  </h3>
                  <ul className="max-h-56 overflow-y-auto space-y-1.5 text-[11px] font-mono text-gray-400">
                    {nodeHint.properties.cluster_member_ids
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean)
                      .map((id) => (
                        <li key={id} className="rounded border border-surface-800 px-2 py-1">
                          {id}
                        </li>
                      ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}

          {state === "not_found" ? (
            <div className="rounded-lg border border-surface-700 bg-surface-900/60 px-4 py-5 text-sm text-gray-400 space-y-2">
              <p className="text-gray-300 font-medium">No graph record for this entity</p>
              <p>
                The graph database does not have a vertex for this ID in tenant{" "}
                <span className="font-mono text-gray-400">{tenantId}</span>. It may be outside the indexed subgraph,
                removed, or not yet ingested.
              </p>
            </div>
          ) : null}

          {state === "error" ? (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
              {errMsg}
            </div>
          ) : null}

          {state === "ready" ? (
            <div className="space-y-6 text-sm">
              {(() => {
                const hops = hopStoryFromLinks(entityId || "", links?.edges || [], links?.nodes || []);
                const story = buildObjectStory(receipts, hold, hops);
                if (!story.length) return null;
                let proving = true;
                return (
                  <section data-testid="object-story" className="space-y-3">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Story
                    </h3>
                    {story.map((row) => {
                      if (row.kind === "hop") {
                        return (
                          <div
                            key={`hop-${row.id}`}
                            data-testid="object-decision-hop"
                            className="rounded border border-surface-800 px-2 py-2"
                          >
                            <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
                              {onSelectEntity ? (
                                <button
                                  type="button"
                                  className="font-mono text-sky-300 hover:underline"
                                  onClick={() => onSelectEntity(row.id)}
                                >
                                  {row.id}
                                </button>
                              ) : (
                                <span className="font-mono text-gray-300">{row.id}</span>
                              )}
                              <span className={isPackFiredDecision(row.outcome) ? "text-amber-200" : "text-gray-400"}>
                                {row.outcome || "—"}
                              </span>
                            </p>
                          </div>
                        );
                      }
                      if (row.kind === "hold") {
                        return (
                          <div
                            key={`hold-${row.at}-${row.outcome}`}
                            data-testid="object-hold"
                            className="rounded border border-amber-900/50 px-2 py-2"
                          >
                            <p className="text-xs text-amber-200/90">
                              held
                              {row.outcome && row.outcome !== "held" ? ` · ${formatCell(row.outcome)}` : ""}
                            </p>
                          </div>
                        );
                      }
                      const why = resolvePackWhy({
                        rule_pack_file: row.receipt.rule_pack_file,
                        rule_hits: row.receipt.rule_hits,
                        evaluate_payload: row.receipt.evaluate_payload ?? null,
                      });
                      const primary = proving && isPackFiredDecision(row.receipt.decision);
                      if (primary) proving = false;
                      return (
                        <div
                          key={row.receipt.trace_id}
                          data-testid={primary ? "object-evaluate" : undefined}
                          className="space-y-1.5 rounded border border-surface-800 px-2 py-2"
                        >
                          <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
                            <span className="text-gray-300">{row.receipt.event_type || "evaluate"}</span>
                            <span className={isPackFiredDecision(row.receipt.decision) ? "text-amber-200" : "text-gray-400"}>
                              {row.receipt.decision || "—"}
                            </span>
                            <span className="text-gray-500">{row.receipt.score ?? "—"}</span>
                            {!primary ? (
                              <span className="text-gray-500 truncate">
                                {why.packId === PACK_WHY_MISSING ? PACK_WHY_MISSING : why.packId}
                                {why.why !== PACK_WHY_MISSING ? ` · ${why.why}` : ""}
                              </span>
                            ) : null}
                          </p>
                          {primary ? (
                            <>
                              <PackWhyStrip {...why} advise={null} />
                              <DeviceIntegrityStrip
                                {...resolveIntegrityPresence({
                                  integrity: row.receipt.integrity,
                                  tags: row.receipt.tags,
                                  evaluate_payload: row.receipt.evaluate_payload ?? null,
                                })}
                              />
                            </>
                          ) : null}
                        </div>
                      );
                    })}
                  </section>
                );
              })()}

              {links?.edges?.length ? (
                <section data-testid="object-links">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                    Links ({links.edges.length})
                  </h3>
                  <ul className="space-y-1.5">
                    {rankRelatedLinks(entityId || "", links.edges, links.attention).map(({ edge: e, other, attention }) => {
                      const why = attention?.reasons?.[0];
                      const receipt = typeof e.properties?.trace_id === "string" ? e.properties.trace_id : "";
                      return (
                        <li
                          key={`${e.from_id}-${e.type}-${e.to_id}`}
                          className="flex justify-between gap-2 rounded border border-surface-800 px-2 py-1.5 text-xs"
                        >
                          <span className="text-gray-400 shrink-0">{e.type}</span>
                          <span className="flex items-center gap-2 min-w-0">
                            {attention ? (
                              <span
                                className={
                                  attention.attend_pack
                                    ? "text-[10px] uppercase tracking-wide text-amber-300"
                                    : "text-[10px] uppercase tracking-wide text-gray-500"
                                }
                              >
                                {attention.attend_pack ? "attend" : "related"}
                              </span>
                            ) : null}
                            {onSelectEntity && other ? (
                              <button
                                type="button"
                                className="font-mono text-sky-300 truncate hover:underline"
                                onClick={() => onSelectEntity(other)}
                              >
                                {other}
                              </button>
                            ) : (
                              <span className="font-mono text-gray-200 truncate">{other}</span>
                            )}
                          </span>
                          {receipt ? (
                            <span className="font-mono text-[10px] text-gray-500 truncate max-w-[40%]" title={receipt}>
                              {receipt}
                            </span>
                          ) : why ? (
                            <span className="text-[10px] text-gray-500 truncate max-w-[40%]">{why}</span>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ) : null}

              {history ? (
                <section data-testid="object-history">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                    Decision history
                  </h3>
                  <p className="text-xs text-gray-400">
                    Last:{" "}
                    <span className="font-mono text-gray-200">{history.last_trace_id || "—"}</span>
                  </p>
                  {history.decisions && history.decisions.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {history.decisions.map((row) => (
                        <li key={row.id} className="flex flex-wrap gap-x-2 text-[11px] text-gray-400">
                          {onSelectEntity ? (
                            <button
                              type="button"
                              className="font-mono text-sky-300 hover:underline"
                              onClick={() => onSelectEntity(row.id)}
                            >
                              {row.outcome || row.id}
                            </button>
                          ) : (
                            <span className="font-mono text-gray-200">{row.outcome || row.id}</span>
                          )}
                          {row.source ? <span>{row.source}</span> : null}
                          {row.trace_id ? (
                            <span className="font-mono text-gray-500">{row.trace_id}</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : history.trace_ids.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {history.trace_ids.map((tid) => (
                        <li key={tid} className="font-mono text-[11px] text-gray-500">
                          {tid}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </section>
              ) : null}

              {data ? (
              <>
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                  Historical transactions ({data.historical_transactions.length})
                </h3>
                {data.historical_transactions.length === 0 ? (
                  <p className="text-gray-500 text-xs">No linked Payment vertices in the 2-hop neighborhood.</p>
                ) : (
                  <ul className="space-y-2 max-h-56 overflow-y-auto">
                    {data.historical_transactions.map((t) => (
                      <li
                        key={t.external_id}
                        className="rounded-lg border border-surface-800 bg-surface-900/80 px-3 py-2 text-xs space-y-1"
                      >
                        <div className="font-mono text-gray-300">{t.external_id}</div>
                        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-gray-500">
                          <span>trace</span>
                          <span className="text-gray-400 text-right">{formatCell(t.trace_id)}</span>
                          <span>amount</span>
                          <span className="text-gray-400 text-right">{formatCell(t.amount)}</span>
                          <span>decision</span>
                          <span className="text-gray-400 text-right">{formatCell(t.decision)}</span>
                          <span>ip</span>
                          <span className="text-gray-400 text-right">{formatCell(t.ip)}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                  IP addresses ({data.ip_addresses.length})
                </h3>
                {data.ip_addresses.length === 0 ? (
                  <p className="text-gray-500 text-xs">No IP-like neighbors or IP properties found.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {data.ip_addresses.map((row) => (
                      <li
                        key={`${row.ip}-${row.source}`}
                        className="flex justify-between gap-2 rounded border border-surface-800 px-2 py-1.5 text-xs"
                      >
                        <span className="font-mono text-brand-200">{row.ip}</span>
                        <span className="text-gray-500 shrink-0">{row.source}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Risk history</h3>
                <ul className="space-y-2">
                  {data.risk_history.map((r, i) => (
                    <li key={`${r.recorded_at}-${i}`} className="rounded-lg border border-surface-800 bg-surface-900/80 px-3 py-2 text-xs space-y-1">
                      <div className="flex justify-between gap-2 text-gray-500">
                        <span>{r.source}</span>
                        <span className="font-mono text-gray-400">{r.recorded_at}</span>
                      </div>
                      <div className="text-gray-300">
                        score: <span className="font-mono text-amber-200/90">{formatCell(r.risk_score)}</span>
                      </div>
                      {Array.isArray(r.risk_factors) && r.risk_factors.length > 0 ? (
                        <ul className="list-disc list-inside text-gray-500">
                          {(r.risk_factors as string[]).map((f) => (
                            <li key={f}>{f}</li>
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>
              </>
              ) : null}
            </div>
          ) : null}
        </div>
      </aside>
  );

  if (embedded) return shell;

  return (
    <div className="fixed inset-0 z-[80] flex justify-end" role="presentation">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-[1px]"
        aria-label="Close context panel"
        onClick={onClose}
      />
      {shell}
    </div>
  );
}
