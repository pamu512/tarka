/** Mirrors orchestrator ``data_sources`` (booleans + ``graph_backend`` string). */
export type EntityProfileDataSources = Record<string, boolean | string>;

export type EntityProfileLifecycleCase = {
  source: string;
  case_id: string;
  status: string;
  priority: number;
  entity_id: string;
  transaction_id: number;
  opened_at: string | null;
} | null;

export type EntityProfileGraphVizNode = {
  id: string;
  kind: string;
  label: string;
};

export type EntityProfileGraphVizLink = {
  source: string;
  target: string;
  rel: string;
};

export type EntityProfileResponse = {
  user_id: string;
  generated_at: string;
  data_sources: EntityProfileDataSources;
  lifecycle_case: EntityProfileLifecycleCase;
  graph_fragment: Record<string, unknown>;
  graph_viz: {
    nodes?: EntityProfileGraphVizNode[];
    links?: EntityProfileGraphVizLink[];
    backend?: string;
    found?: boolean;
  };
  duckdb_metrics: Record<string, unknown>;
  shadow_executive_summary: Record<string, unknown>;
};
