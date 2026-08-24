/**
 * First-open investigator strip: native device integrity.
 * Always rendered. If a field is absent, show "missing" — never hide, never invent.
 */

import { DEVICE_INTEGRITY_MISSING } from "../../utils/deviceIntegrity";

function Value({ testId, value }: { testId: string; value: string }) {
  return (
    <p data-testid={testId} className="text-sm text-gray-200 leading-snug">
      {value === DEVICE_INTEGRITY_MISSING ? (
        <span className="italic font-medium text-gray-400">{DEVICE_INTEGRITY_MISSING}</span>
      ) : (
        value
      )}
    </p>
  );
}

export function DeviceIntegrityStrip({
  rooted,
  jailbroken,
  biometrics,
}: {
  rooted: string;
  jailbroken: string;
  biometrics: string;
}) {
  return (
    <section
      data-testid="device-integrity-strip"
      aria-label="Device integrity"
      className="border-b border-surface-700 bg-surface-950/90 px-4 py-2.5"
    >
      <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-gray-500">Device integrity</p>
      <div className="mt-1.5 grid grid-cols-3 gap-3 min-w-0">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-gray-500">Rooted</p>
          <Value testId="device-integrity-rooted" value={rooted} />
        </div>
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-gray-500">Jailbroken</p>
          <Value testId="device-integrity-jailbroken" value={jailbroken} />
        </div>
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-gray-500">Biometrics</p>
          <Value testId="device-integrity-biometrics" value={biometrics} />
        </div>
      </div>
    </section>
  );
}
