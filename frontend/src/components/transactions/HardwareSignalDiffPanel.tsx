import type { TransactionRow } from "@/domain/transactionRow";
import {
  VISUAL_DIFF_HIGHLIGHT_THRESHOLD,
  hardwareSimilarityRatio,
} from "@/domain/hardwareSignals";

type Props = {
  left: TransactionRow;
  right: TransactionRow;
};

export function HardwareSignalDiffPanel({ left, right }: Props) {
  const hwA = left.hardwareSignals ?? {};
  const hwB = right.hardwareSignals ?? {};
  const sim = hardwareSimilarityRatio(hwA, hwB);
  const strongOverlap = sim.ratio >= VISUAL_DIFF_HIGHLIGHT_THRESHOLD;

  const allKeys = [...new Set([...Object.keys(hwA), ...Object.keys(hwB)])].sort((a, b) =>
    a.localeCompare(b),
  );

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-900/70 overflow-hidden"
      aria-label="Hardware signal visual diff"
    >
      <div className="px-4 py-3 border-b border-surface-700 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-200">Visual diff — hardware signals</h2>
          <p className="text-[11px] text-gray-500 mt-1 font-mono truncate max-w-[48rem]">
            <span className="text-gray-400">{left.traceId}</span>
            <span className="mx-2 text-gray-600">vs</span>
            <span className="text-gray-400">{right.traceId}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold tabular-nums ${
              strongOverlap
                ? "bg-emerald-500/20 text-emerald-200 border border-emerald-500/35"
                : "bg-surface-800 text-gray-400 border border-surface-600"
            }`}
          >
            {(sim.ratio * 100).toFixed(0)}% overlap
          </span>
          {strongOverlap ? (
            <span className="text-[11px] text-emerald-400/90">
              ≥{Math.round(VISUAL_DIFF_HIGHLIGHT_THRESHOLD * 100)}% — matching fields highlighted
            </span>
          ) : (
            <span className="text-[11px] text-gray-500">
              Below {Math.round(VISUAL_DIFF_HIGHLIGHT_THRESHOLD * 100)}% — differences emphasized
            </span>
          )}
        </div>
      </div>

      {allKeys.length === 0 ? (
        <p className="px-4 py-6 text-sm text-gray-500">
          No hardware signal maps on these rows — extend the feed payload with{" "}
          <code className="text-gray-400">device_context</code> /{" "}
          <code className="text-gray-400">hardware_signals</code> (see live grid seed).
        </p>
      ) : (
        <div className="overflow-x-auto max-h-[min(55vh,28rem)] overflow-y-auto">
          <table className="w-full text-left text-[13px]">
            <thead className="sticky top-0 z-10 bg-surface-950/95 border-b border-surface-700 text-[11px] uppercase tracking-wide text-gray-500">
              <tr>
                <th className="py-2.5 px-3 font-medium w-[28%]">Signal</th>
                <th className="py-2.5 px-3 font-medium w-[36%]">Transaction A</th>
                <th className="py-2.5 px-3 font-medium w-[36%]">Transaction B</th>
              </tr>
            </thead>
            <tbody>
              {allKeys.map((key) => {
                const va = hwA[key];
                const vb = hwB[key];
                const hasBoth = va !== undefined && vb !== undefined;
                const isMatch = hasBoth && va === vb;
                const highlightRow = strongOverlap && isMatch;
                const mismatchEmphasis = hasBoth && !isMatch;
                return (
                  <tr
                    key={key}
                    className={`border-b border-surface-800/90 ${
                      highlightRow
                        ? "bg-emerald-500/[0.12] ring-1 ring-inset ring-emerald-500/25"
                        : mismatchEmphasis && strongOverlap
                          ? "bg-amber-500/[0.06]"
                          : mismatchEmphasis
                            ? "bg-rose-500/[0.06]"
                            : ""
                    }`}
                  >
                    <td className="py-2 px-3 font-mono text-[11px] text-gray-400 align-top break-all">{key}</td>
                    <td className="py-2 px-3 font-mono text-[12px] text-gray-200 align-top break-all">
                      {va ?? <span className="text-gray-600 italic">missing</span>}
                    </td>
                    <td className="py-2 px-3 font-mono text-[12px] text-gray-200 align-top break-all">
                      {vb ?? <span className="text-gray-600 italic">missing</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="px-4 py-2 border-t border-surface-800 text-[11px] text-gray-600">
        Comparable keys: {sim.comparableKeys.length} · Matches: {sim.matchingKeys.size}
      </div>
    </section>
  );
}
