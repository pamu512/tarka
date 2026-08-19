/**
 * First-open investigator strip: which pack fired + one why.
 * Always rendered. If the pack reason is absent, show "missing" — never hide, never invent.
 */

import { PACK_WHY_MISSING, type PackWhyView } from "../../utils/packWhy";

export function PackWhyStrip({ packId, packName, why, advise }: PackWhyView) {
  const packLabel = packName !== PACK_WHY_MISSING && packName !== packId ? `${packName} (${packId})` : packId;

  return (
    <section
      data-testid="pack-why-strip"
      aria-label="Pack that fired and why"
      className="border-b border-surface-700 bg-surface-950/90 px-4 py-2.5"
    >
      <div className="flex flex-col gap-1 min-w-0">
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-gray-500">Pack</p>
        <p data-testid="pack-why-pack" className="text-sm font-semibold text-gray-100 truncate">
          {packLabel === PACK_WHY_MISSING ? (
            <span className="italic font-medium text-gray-400">{PACK_WHY_MISSING}</span>
          ) : (
            packLabel
          )}
        </p>
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-gray-500 mt-1">Why</p>
        <p data-testid="pack-why-reason" className="text-sm text-gray-200 leading-snug">
          {why === PACK_WHY_MISSING ? (
            <span className="italic font-medium text-gray-400">{PACK_WHY_MISSING}</span>
          ) : (
            why
          )}
        </p>
        {advise ? (
          <p data-testid="pack-why-advise" className="text-xs text-gray-400 leading-snug mt-1">
            <span className="font-semibold uppercase tracking-wide text-gray-500 mr-1.5">Advise</span>
            {advise}
          </p>
        ) : null}
      </div>
    </section>
  );
}
