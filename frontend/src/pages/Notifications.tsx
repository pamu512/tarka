import { PageTitle } from "../components/PageTitle";

/** Prototype inbox: actionable vs informational until a notifications API exists. */
export default function Notifications() {
  return (
    <div className="p-6 space-y-8 max-w-3xl animate-fade-in">
      <PageTitle module="notifications">Notifications</PageTitle>
      <p className="text-sm text-gray-500 -mt-4">
        Demo data — wire to your event bus or case webhooks when ready. Actionable items are highlighted for
        human-in-the-loop work; updates are informational only.
      </p>

      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-amber-500/90">Needs attention</h2>
        <ul className="rounded-xl border border-surface-700 bg-surface-900 divide-y divide-surface-700">
          <li className="px-4 py-3 flex gap-3">
            <span className="mt-0.5 h-2 w-2 rounded-full bg-amber-400 shrink-0" aria-hidden />
            <div>
              <p className="text-sm text-gray-200">3 cases exceed SLA window</p>
              <p className="text-xs text-gray-500 mt-0.5">Open the Cases queue to triage.</p>
            </div>
          </li>
          <li className="px-4 py-3 flex gap-3">
            <span className="mt-0.5 h-2 w-2 rounded-full bg-amber-400 shrink-0" aria-hidden />
            <div>
              <p className="text-sm text-gray-200">Rule pack “velocity_guard” has unpublished draft</p>
              <p className="text-xs text-gray-500 mt-0.5">Review in Rules before promoting.</p>
            </div>
          </li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">Updates</h2>
        <ul className="rounded-xl border border-surface-700 bg-surface-900 divide-y divide-surface-700">
          <li className="px-4 py-3">
            <p className="text-sm text-gray-300">Weekly analytics export completed</p>
            <p className="text-xs text-gray-600 mt-0.5">2 hours ago</p>
          </li>
          <li className="px-4 py-3">
            <p className="text-sm text-gray-300">Integration “sandbox_ingress” health check OK</p>
            <p className="text-xs text-gray-600 mt-0.5">Yesterday</p>
          </li>
        </ul>
      </section>
    </div>
  );
}
