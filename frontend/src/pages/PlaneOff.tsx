import type { ReactElement } from "react";
import { Link } from "react-router";

import { leanHomePath, type PlaneId } from "../config/leanNav";
import { PageTitle } from "../components/PageTitle";

const COPY: Record<PlaneId, { title: string; body: string; module: "graph" | "investigation" | "analytics" }> = {
  graph: {
    title: "Graph plane off",
    module: "graph",
    body: "GRAPH_SERVICE_URL is empty, so the graph plane is not deployed. This is not an outage.",
  },
  advise: {
    title: "Advise plane off",
    module: "investigation",
    body: "Investigation / Advise is not deployed (investigation-agent URL is empty). This is not an outage.",
  },
  signals: {
    title: "Signals plane off",
    module: "analytics",
    body: "SIGNAL_API_URL is empty, so feature / ML / calibration chrome is not deployed. This is not an outage.",
  },
};

export default function PlaneOff({ plane }: { plane: PlaneId }): ReactElement {
  const copy = COPY[plane];
  return (
    <div className="mx-auto max-w-lg px-6 py-16 space-y-4">
      <PageTitle module={copy.module}>{copy.title}</PageTitle>
      <p className="text-sm text-gray-400" role="status">
        Plane off. {copy.body} Bring the plane up with the matching compose overlay, then rebuild the desk
        with the plane URL set.
      </p>
      <Link
        to={leanHomePath()}
        className="inline-flex items-center justify-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-500 transition-colors"
      >
        Back to desk
      </Link>
    </div>
  );
}
