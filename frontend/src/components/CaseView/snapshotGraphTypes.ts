/** Persisted ``graph_snapshot`` wire shape (orchestrator ``build_graph_viz``). */

export type GraphSnapshotNode = {
  id: string;
  kind?: string;
  label?: string;
  /** Shared device fingerprint when supplied by the orchestrator — enables UI clustering. */
  device_hash?: string;
  properties?: Record<string, unknown>;
};

export type GraphSnapshotLink = {
  source: string;
  target: string;
  rel?: string;
};
