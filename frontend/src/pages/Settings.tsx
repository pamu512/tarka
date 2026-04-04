import { PageTitle } from "../components/PageTitle";
import { useTheme, type ThemePreference } from "../context/ThemeContext";

export default function Settings() {
  const { preference, setPreference, effective } = useTheme();

  return (
    <div className="p-6 space-y-8 max-w-2xl animate-fade-in">
      <PageTitle module="settings">Settings</PageTitle>
      <p className="text-sm text-gray-500 -mt-4">
        Account and workspace preferences placeholder — connect to your identity provider and tenant config when
        available.
      </p>

      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-300">Appearance</h2>
          <p className="text-xs text-gray-500 mt-1">
            Choose light, dark, or match your system. Use the <strong className="text-gray-400">Settings</strong> icon or{" "}
            <strong className="text-gray-400">Account</strong> menu in the top bar for quick access. The sidebar uses the
            vector Tarka mark (black in light theme, white in dark) from{" "}
            <code className="text-gray-600">/tarka-icon.svg</code>. See{" "}
            <strong className="text-gray-400">Help</strong>{" "}
            for a full product tour.
          </p>
        </div>
        <fieldset className="space-y-2">
          <legend className="sr-only">Color theme</legend>
          {(
            [
              ["system", "System default", "Follows OS light/dark and updates when it changes."],
              ["light", "Light", "Bright surfaces and high-contrast text for daytime use."],
              ["dark", "Dark", "Original console look, easier in low light."],
            ] as const
          ).map(([value, label, hint]) => (
            <label
              key={value}
              className="flex items-start gap-3 rounded-lg border border-surface-700/80 bg-surface-950/40 px-3 py-2.5 cursor-pointer hover:border-surface-600"
            >
              <input
                type="radio"
                name="theme"
                value={value}
                checked={preference === value}
                onChange={() => setPreference(value as ThemePreference)}
                className="mt-1 rounded-full border-surface-600 text-brand-500 focus:ring-brand-500/40"
              />
              <span>
                <span className="block text-sm font-medium text-gray-200">{label}</span>
                <span className="block text-xs text-gray-600 mt-0.5">{hint}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <p className="text-[11px] text-gray-600">
          Active now: <span className="text-gray-400 capitalize">{effective}</span>
          {preference === "system" ? " (from system)" : ""}.
        </p>
      </div>

      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-2">
        <h2 className="text-sm font-semibold text-gray-300">Account</h2>
        <p className="text-xs text-gray-500">Signed-in user and session (prototype — not connected).</p>
      </div>

      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-2">
        <h2 className="text-sm font-semibold text-gray-300">Workspace</h2>
        <p className="text-xs text-gray-500">Tenant defaults, time zone, and notification routing.</p>
      </div>

      <div className="rounded-xl border border-dashed border-surface-600 bg-surface-900/50 p-4 space-y-2 opacity-80">
        <h2 className="text-sm font-semibold text-gray-400">API keys</h2>
        <p className="text-xs text-gray-600">Coming soon — manage programmatic access here.</p>
      </div>
    </div>
  );
}
