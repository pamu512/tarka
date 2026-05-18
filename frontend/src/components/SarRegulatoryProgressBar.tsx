import type { SarFilingIntentDetail, SarIntentDetailResponse } from "../api/client";
import { Link } from "react-router-dom";
import {
  evaluateSarFilingReadinessFromDetail,
  evaluateSarFilingReadinessFromIntentSummary,
  type SarFilingCheckRow,
} from "../utils/sarFilingCompleteness";

type WorkspaceProps = {
  variant: "workspace";
  detail: SarIntentDetailResponse;
  /** When notes are editable, pass current draft so the bar updates before save. */
  draftNotesHtml?: string;
};

type CaseSummaryProps = {
  variant: "case_summary";
  intent: SarFilingIntentDetail;
  workspaceHref: string;
};

type Props = WorkspaceProps | CaseSummaryProps;

function stateStyles(state: SarFilingCheckRow["state"]): { row: string; badge: string; symbol: string } {
  switch (state) {
    case "satisfied":
      return {
        row: "border-emerald-500/20 bg-emerald-950/25",
        badge: "text-emerald-200/95 bg-emerald-900/50 border-emerald-500/35",
        symbol: "text-emerald-300",
      };
    case "missing":
      return {
        row: "border-amber-500/40 bg-amber-950/30",
        badge: "text-amber-100 bg-amber-900/45 border-amber-500/45",
        symbol: "text-amber-200",
      };
    case "pending":
      return {
        row: "border-surface-600/80 bg-surface-950/40",
        badge: "text-gray-400 bg-surface-900/70 border-surface-600",
        symbol: "text-gray-500",
      };
    case "unknown":
      return {
        row: "border-sky-500/25 bg-sky-950/20",
        badge: "text-sky-200/90 bg-sky-950/40 border-sky-500/35",
        symbol: "text-sky-300/90",
      };
    default:
      return {
        row: "border-surface-600 bg-surface-950/40",
        badge: "text-gray-400 border-surface-600",
        symbol: "text-gray-500",
      };
  }
}

function statusWord(state: SarFilingCheckRow["state"]): string {
  switch (state) {
    case "satisfied":
      return "Complete";
    case "missing":
      return "Missing";
    case "pending":
      return "Not yet required";
    case "unknown":
      return "Check workspace";
    default:
      return "—";
  }
}

function RowSymbol(state: SarFilingCheckRow["state"]): string {
  switch (state) {
    case "satisfied":
      return "✓";
    case "missing":
      return "!";
    case "pending":
      return "—";
    case "unknown":
      return "?";
    default:
      return "—";
  }
}

export function SarRegulatoryProgressBar(props: Props) {
  const title = props.variant === "workspace" ? "SAR filing readiness" : "SAR filing readiness (summary)";
  const readiness =
    props.variant === "workspace"
      ? evaluateSarFilingReadinessFromDetail(props.detail, props.draftNotesHtml)
      : evaluateSarFilingReadinessFromIntentSummary(props.intent);

  const { percentComplete, rows, missingLabels } = readiness;
  const safePct = Math.min(100, Math.max(0, percentComplete));

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 space-y-3"
      aria-labelledby="sar-regulatory-progress-heading"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="sar-regulatory-progress-heading" className="text-sm font-semibold text-gray-100">
            {title}
          </h2>
          <p className="text-xs text-gray-500 mt-0.5 max-w-prose">
            Which SAR filing elements are complete, missing, or not yet required at this stage (separate from transmit
            pipeline steps).
          </p>
        </div>
        <div className="text-right space-y-1 min-w-[8rem]">
          <div className="text-[11px] uppercase tracking-wide text-gray-500">Overall</div>
          <div className="text-lg font-semibold tabular-nums text-gray-100">{safePct}%</div>
        </div>
      </div>

      <div className="space-y-1.5">
        <div
          className="h-2 rounded-full bg-surface-800 overflow-hidden border border-surface-700"
          role="progressbar"
          aria-valuenow={safePct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`SAR filing readiness ${safePct} percent`}
        >
          <div
            className="h-full rounded-full bg-gradient-to-r from-brand-600/90 to-emerald-600/85 transition-[width] duration-300 ease-out"
            style={{ width: `${safePct}%` }}
          />
        </div>
        {missingLabels.length > 0 ? (
          <p className="text-xs text-amber-200/90">
            <span className="font-medium text-amber-100/95">Still missing: </span>
            {missingLabels.join(" · ")}
          </p>
        ) : (
          <p className="text-xs text-emerald-200/85">No blocking filing gaps for evaluated items.</p>
        )}
      </div>

      <ul className="space-y-2 list-none p-0 m-0">
        {rows.map((row) => {
          const st = stateStyles(row.state);
          return (
            <li
              key={row.id}
              className={`rounded-lg border px-3 py-2.5 text-sm ${st.row}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex items-start gap-2 min-w-0">
                  <span className={`mt-0.5 font-semibold ${st.symbol}`} aria-hidden>
                    {RowSymbol(row.state)}
                  </span>
                  <div className="min-w-0">
                    <div className="font-medium text-gray-100 leading-snug">{row.label}</div>
                    <div className="text-[11px] text-gray-500 mt-0.5 leading-relaxed">{row.regulatoryHint}</div>
                  </div>
                </div>
                <span
                  className={`shrink-0 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded border ${st.badge}`}
                >
                  {statusWord(row.state)}
                </span>
              </div>
              {row.remediation ? (
                <p className="text-xs text-gray-400 mt-2 pl-6 leading-relaxed border-l border-surface-700/80">
                  {row.remediation}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>

      {props.variant === "case_summary" ? (
        <p className="text-xs text-gray-500 pt-1">
          <Link className="text-sky-400/95 hover:underline font-medium" to={props.workspaceHref}>
            Open SAR intent workspace
          </Link>{" "}
          for the full checklist (narrative length, FinCEN digest when locked, and other workspace-only fields).
        </p>
      ) : null}
    </section>
  );
}
