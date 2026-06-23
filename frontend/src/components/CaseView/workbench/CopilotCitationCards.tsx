import { Link } from "react-router-dom";
import type { InvestigationEvidenceSummaryCitation } from "../../../api/client";

type CopilotCitationCardsProps = {
  citations: InvestigationEvidenceSummaryCitation[];
  loading?: boolean;
  error?: string | null;
};

/** E02 — structured citation cards for the embedded copilot rail. */
export function CopilotCitationCards({ citations, loading, error }: CopilotCitationCardsProps) {
  if (loading) {
    return (
      <p className="text-[11px] text-gray-500 px-3 py-2" aria-busy>
        Loading citations…
      </p>
    );
  }
  if (error) {
    return (
      <p className="text-[11px] text-rose-400 px-3 py-2 whitespace-pre-wrap" role="alert">
        {error}
      </p>
    );
  }
  if (!citations.length) {
    return (
      <p className="text-[11px] text-gray-600 px-3 py-2">
        Ask the copilot a question, then run evidence summary for citation anchors.
      </p>
    );
  }

  return (
    <ul className="space-y-2 px-3 py-2 max-h-48 overflow-y-auto" aria-label="Copilot citations">
      {citations.map((c, i) => (
        <li
          key={`${c.claim_index}-${i}`}
          className="rounded-lg border border-surface-700/80 bg-surface-950/60 px-2.5 py-2 text-[11px] leading-snug"
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 mb-1">
            <span className="font-mono text-brand-300">#{c.claim_index}</span>
            <span
              className={`uppercase text-[10px] font-semibold tracking-wide ${
                c.confidence_label === "high"
                  ? "text-emerald-400/90"
                  : c.confidence_label === "medium"
                    ? "text-amber-300/90"
                    : "text-gray-500"
              }`}
            >
              {c.confidence_label}
            </span>
            {c.supported === true ? (
              <span className="text-[10px] text-emerald-500/80">supported</span>
            ) : c.supported === false ? (
              <span className="text-[10px] text-rose-400/80">unverified</span>
            ) : null}
            <span className="text-gray-600 font-mono text-[10px]">{c.source}</span>
          </div>
          <p className="text-gray-300">{c.text}</p>
          {c.resolves_to?.length ? (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {c.resolves_to.map((r, j) => (
                <span
                  key={`${r.artifact}-${r.id}-${j}`}
                  className="rounded bg-surface-900 px-1.5 py-0.5 font-mono text-[10px] text-gray-500"
                  title={`${r.artifact} anchor`}
                >
                  {r.artifact}:{r.id}
                </span>
              ))}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function CounterTransparencyChip({
  counterName,
  title,
  opsLink,
}: {
  counterName: string;
  title?: string;
  opsLink?: string;
}) {
  const href = opsLink ?? `/ops/counters#${encodeURIComponent(counterName)}`;
  return (
    <Link
      to={href}
      className="inline-flex items-center gap-1 rounded bg-surface-800/80 px-1.5 py-0.5 font-mono text-[10px] text-brand-300/90 hover:text-brand-200 border border-surface-700/80"
      title={title ?? counterName}
    >
      {counterName}
      <span className="text-gray-600" aria-hidden>
        ↗
      </span>
    </Link>
  );
}
