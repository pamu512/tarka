"use client";

import type { EntityRiskResult } from "../../api/client";
import type { InferenceContext } from "../../api/client";
import { parseConnectivityNeighborCount } from "../../utils/graphConnectivity";

function MonoRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-6 text-[11px] font-mono tabular-nums">
      <span className="text-gray-500 shrink-0">{k}</span>
      <span className="text-gray-100 text-right">{v}</span>
    </div>
  );
}

/** Graph / “mule score” lineage — JanusGraph facts when present on payload or embedded in risk_factors. */
export function GraphMetricHoverBody({
  risk,
  inference,
}: {
  risk: EntityRiskResult | null;
  inference?: InferenceContext | null;
}) {
  if (!risk && !inference) {
    return (
      <p className="text-gray-500 text-[11px]">No graph entity risk payload and no evaluate graph fields.</p>
    );
  }

  const explicitOneHop = risk?.neighbors_1hop;
  const parsedOneHop = parseConnectivityNeighborCount(risk?.risk_factors);
  const oneHop = explicitOneHop ?? parsedOneHop;

  const traversalMs = risk?.graph_traversal_ms;

  return (
    <div className="space-y-2">
      {risk ? (
        <>
          <MonoRow k="1-hop neighbor count" v={oneHop != null ? String(oneHop) : "—"} />
          <MonoRow
            k="JanusGraph traversal"
            v={traversalMs != null && Number.isFinite(traversalMs) ? `${traversalMs.toFixed(2)} ms` : "—"}
          />
          <MonoRow k="Community size (BFS cap)" v={String(risk.community_size)} />
          <MonoRow k="Flagged neighbors" v={String(risk.connected_flagged_count)} />
          <p className="text-[10px] text-gray-600 pt-1 border-t border-surface-700">
            Raw factors: {risk.risk_factors?.length ? risk.risk_factors.join(" · ") : "—"}
          </p>
        </>
      ) : (
        <p className="text-[10px] text-gray-500">Janus entity payload missing — showing evaluate graph slice only.</p>
      )}
      {inference ? (
        <div className={`space-y-2 ${risk ? "pt-2 border-t border-surface-700" : ""}`}>
          <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-gray-500">Evaluate bundle</p>
          <MonoRow k="graph_risk_score" v={inference.graph_risk_score.toFixed(6)} />
          <p className="text-[10px] text-gray-600 leading-snug">
            graph_risk_reasons:{" "}
            {inference.graph_risk_reasons?.length ? inference.graph_risk_reasons.join(" · ") : "—"}
          </p>
        </div>
      ) : null}
    </div>
  );
}

export function VelocityHoverBody({ ctx }: { ctx: InferenceContext | null }) {
  if (!ctx) return <p className="text-gray-500 text-[11px]">No inference bundle.</p>;
  return (
    <div className="space-y-2">
      <MonoRow k="Velocity 5m" v={String(ctx.velocity_events_5m)} />
      <MonoRow k="Velocity 1h" v={String(ctx.velocity_events_1h)} />
      <MonoRow k="Velocity 24h" v={String(ctx.velocity_events_24h)} />
      <MonoRow k="External signal" v={`${(ctx.external_signal_score * 100).toFixed(1)}%`} />
    </div>
  );
}

export function GeoHoverBody({ ctx }: { ctx: InferenceContext | null }) {
  if (!ctx) return <p className="text-gray-500 text-[11px]">No inference bundle.</p>;
  return (
    <div className="space-y-2">
      <MonoRow k="Geo consistency risk" v={ctx.geo_consistency_risk.toFixed(3)} />
      <MonoRow k="Impossible travel (proxy)" v={ctx.impossible_travel_risk.toFixed(3)} />
      <MonoRow k="Location confidence" v={`${(ctx.location_confidence * 100).toFixed(1)}%`} />
    </div>
  );
}

export function QueueScoreHoverBody({ score }: { score: number | null | undefined }) {
  return (
    <div className="space-y-2">
      <MonoRow k="case.queue_score" v={score != null && Number.isFinite(score) ? score.toFixed(4) : "—"} />
      <p className="text-[10px] text-gray-600 leading-snug">
        Relative backlog priority — surfaced for routing and SLA ordering in the case queue.
      </p>
    </div>
  );
}

export function InferenceIntegrityHoverBody({ ctx }: { ctx: InferenceContext }) {
  return (
    <div className="space-y-2">
      <MonoRow k="integrity_confidence" v={ctx.integrity_confidence.toFixed(6)} />
      <MonoRow k="confidence_tier" v={`${ctx.confidence_tier} · ${ctx.confidence_tier_label}`} />
      <MonoRow k="calibration_profile" v={`${ctx.calibration_profile}@${ctx.calibration_profile_version}`} />
      <MonoRow k="expected_calibration_version" v={String(ctx.expected_calibration_version)} />
      <MonoRow k="source.calibration" v={ctx.confidence_sources.calibration} />
    </div>
  );
}

export function InferenceTamperHoverBody({ ctx }: { ctx: InferenceContext }) {
  return (
    <div className="space-y-2">
      <MonoRow k="tamper_risk" v={ctx.tamper_risk.toFixed(6)} />
      <MonoRow k="source.counter" v={ctx.confidence_sources.counter} />
      <MonoRow k="schema_version" v={ctx.schema_version} />
    </div>
  );
}

export function InferenceReplayHoverBody({ ctx }: { ctx: InferenceContext }) {
  return (
    <div className="space-y-2">
      <MonoRow k="replay_risk" v={ctx.replay_risk.toFixed(6)} />
      <MonoRow k="source.counter" v={ctx.confidence_sources.counter} />
    </div>
  );
}

export function InferenceNetworkTrustHoverBody({ ctx }: { ctx: InferenceContext }) {
  return (
    <div className="space-y-2">
      <MonoRow k="network_trust" v={ctx.network_trust.toFixed(6)} />
      <MonoRow k="colocation_risk" v={ctx.colocation_risk.toFixed(6)} />
      <MonoRow k="copresence_risk" v={ctx.copresence_risk.toFixed(6)} />
    </div>
  );
}

export function InferenceGeoConsistencyHoverBody({ ctx }: { ctx: InferenceContext }) {
  return (
    <div className="space-y-2">
      <MonoRow k="geo_consistency_risk" v={ctx.geo_consistency_risk.toFixed(6)} />
      <MonoRow k="location_confidence" v={`${(ctx.location_confidence * 100).toFixed(2)}%`} />
      <MonoRow k="source.location" v={ctx.confidence_sources.location} />
    </div>
  );
}

export function InferenceColocationHoverBody({ ctx }: { ctx: InferenceContext }) {
  return (
    <div className="space-y-2">
      <MonoRow k="colocation_risk" v={ctx.colocation_risk.toFixed(6)} />
      <MonoRow k="copresence_risk" v={ctx.copresence_risk.toFixed(6)} />
      <MonoRow k="network_trust" v={ctx.network_trust.toFixed(6)} />
    </div>
  );
}

export function InferenceImpossibleTravelHoverBody({ ctx }: { ctx: InferenceContext }) {
  return (
    <div className="space-y-2">
      <MonoRow k="impossible_travel_risk" v={ctx.impossible_travel_risk.toFixed(6)} />
      <MonoRow k="geo_consistency_risk" v={ctx.geo_consistency_risk.toFixed(6)} />
      <MonoRow k="location_confidence" v={`${(ctx.location_confidence * 100).toFixed(2)}%`} />
    </div>
  );
}

export function ExternalSignalHoverBody({ ctx }: { ctx: InferenceContext }) {
  return (
    <div className="space-y-2">
      <MonoRow k="external_signal_score" v={`${(ctx.external_signal_score * 100).toFixed(4)}%`} />
      <MonoRow k="providers" v={ctx.external_signal_providers.length ? ctx.external_signal_providers.join(", ") : "—"} />
      <MonoRow k="policy_experiment_id" v={ctx.policy_experiment_id ?? "—"} />
    </div>
  );
}
