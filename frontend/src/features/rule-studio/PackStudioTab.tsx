import { lazy, Suspense, useEffect, useState } from "react";
import { ApiRequestError, rules } from "../../api/client";
import { useTenantEnvironment } from "../../context/TenantEnvironmentContext";
import { PackFormEditor } from "./editors/PackFormEditor";
import { DryRunPanel } from "./preview/DryRunPanel";
import { ValidatePanel } from "./preview/ValidatePanel";
import { useAuthorCatalog } from "./registry/useAuthorCatalog";
import { usePackDraftStore } from "./store/packDraftStore";

const JsonTab = lazy(() => import("./escape-hatch/JsonTab"));

type StudioSubTab = "form" | "json" | "preview";

function isLiveMode(mode: string | undefined): boolean {
  // Server treats missing mode as active.
  return mode === undefined || mode === "" || mode === "active";
}

function suggestSuffixedName(name: string): string {
  const base = name.replace(/_studio_\d+$/, "") || name;
  return `${base}_studio_2`;
}

function extractPackResponse(res: unknown): { file?: string; pack?: unknown } {
  if (!res || typeof res !== "object") return {};
  const r = res as Record<string, unknown>;
  return {
    file: typeof r.file === "string" ? r.file : undefined,
    pack: r.pack,
  };
}

export default function PackStudioTab() {
  const { tenantId } = useTenantEnvironment();
  const { fields } = useAuthorCatalog(tenantId);
  const draft = usePackDraftStore((s) => s.draft);
  const dirty = usePackDraftStore((s) => s.dirty);
  const loadFromJson = usePackDraftStore((s) => s.loadFromJson);
  const hydrateFromServerPack = usePackDraftStore((s) => s.hydrateFromServerPack);
  const compileForSave = usePackDraftStore((s) => s.compileForSave);
  const reset = usePackDraftStore((s) => s.reset);
  const setPackMeta = usePackDraftStore((s) => s.setPackMeta);
  const addRule = usePackDraftStore((s) => s.addRule);

  const [subTab, setSubTab] = useState<StudioSubTab>("form");
  const [packs, setPacks] = useState<Array<Record<string, unknown>>>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void rules.list().then((res) => {
      setPacks((res.packs ?? []) as unknown as Array<Record<string, unknown>>);
    }).catch(() => setPacks([]));
  }, []);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const liveLocked = isLiveMode(draft.mode);

  const loadPack = (raw: Record<string, unknown>) => {
    const file =
      (typeof raw._file === "string" && raw._file) ||
      (typeof raw.file === "string" && raw.file) ||
      undefined;
    const { _file, ...rest } = raw;
    void _file;
    loadFromJson({ ...rest, file });
    setMessage(null);
    setError(null);
  };

  const doCreate = async (name: string, packBody: Record<string, unknown>, retried = false) => {
    try {
      const res = await rules.create(
        {
          name,
          rules: (packBody.rules as unknown[]) ?? [],
          tag_rules: (packBody.tag_rules as unknown[]) ?? [],
        },
        tenantId,
      );
      const { file, pack } = extractPackResponse(res);
      if (pack) {
        hydrateFromServerPack(
          typeof file === "string" ? { ...(pack as object), file } : pack,
        );
      }
      setMessage(`Saved as Observe draft${file ? ` (${file})` : ""}.`);
      setError(null);
      return true;
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 409 && !retried) {
        const suggested = suggestSuffixedName(name);
        if (confirm(`Name collision. Retry as "${suggested}"?`)) {
          setPackMeta({ name: suggested });
          return doCreate(suggested, { ...packBody, name: suggested }, true);
        }
      }
      setError(e instanceof Error ? e.message : "Save failed");
      return false;
    }
  };

  const saveInPlace = async () => {
    if (liveLocked) return;
    const file = draft.file;
    if (!file) {
      setError("No pack file to update; use Save as new Observe draft.");
      return;
    }
    setBusy(true);
    try {
      const compiled = compileForSave() as Record<string, unknown>;
      const res = await rules.update(
        file,
        {
          name: String(compiled.name ?? draft.name ?? "studio_draft"),
          rules: (compiled.rules as unknown[]) ?? [],
          tag_rules: (compiled.tag_rules as unknown[]) ?? [],
        },
        tenantId,
      );
      const { pack } = extractPackResponse(res);
      if (pack) hydrateFromServerPack({ ...(pack as object), file });
      setMessage("Saved to shadow.");
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  };

  const saveAsNewDraft = async () => {
    setBusy(true);
    try {
      const compiled = compileForSave() as Record<string, unknown>;
      let name = String(compiled.name ?? draft.name ?? "studio_draft");
      if (liveLocked) {
        name = suggestSuffixedName(name);
        setPackMeta({ name });
      }
      await doCreate(name, { ...compiled, name });
    } finally {
      setBusy(false);
    }
  };

  const newDraft = () => {
    reset();
    setPackMeta({ name: "studio_draft", mode: "shadow" });
    addRule();
    setMessage(null);
    setError(null);
  };

  return (
    <div className="p-6 space-y-4 max-w-5xl" data-testid="pack-studio-tab">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-100">Pack Form Studio</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Compiles to pack JSON and saves Observe (shadow) drafts only. Promote stays on the desk.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={newDraft}
            className="text-xs px-3 py-1.5 rounded bg-surface-700 hover:bg-surface-600 text-gray-200 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            New draft
          </button>
          <label className="text-xs text-gray-400 flex items-center gap-1">
            Open pack
            <select
              aria-label="Open pack"
              className="bg-surface-800 border border-surface-600 text-gray-200 text-xs rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
              defaultValue=""
              onChange={(e) => {
                const file = e.target.value;
                if (!file) return;
                const pack = packs.find(
                  (p) => p._file === file || p.file === file || p.name === file,
                );
                if (pack) loadPack(pack);
              }}
            >
              <option value="">Select...</option>
              {packs.map((p, i) => {
                const file = String(p._file ?? p.file ?? p.name ?? i);
                return (
                  <option key={file} value={file}>
                    {String(p.name ?? file)}
                  </option>
                );
              })}
            </select>
          </label>
        </div>
      </div>

      {liveLocked && draft.file && (
        <div
          role="status"
          className="text-xs text-amber-200 border border-amber-700/50 rounded px-3 py-2 bg-amber-950/30"
        >
          Live packs can&apos;t be edited in place; saving would silently demote them. Use Save as
          new Observe draft.
        </div>
      )}

      <div className="flex gap-1 bg-surface-900 border border-surface-700 rounded-lg p-1 w-fit" role="tablist" aria-label="Studio panels">
        {(
          [
            ["form", "Form"],
            ["json", "JSON"],
            ["preview", "Preview"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={subTab === id}
            onClick={() => setSubTab(id)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md ${
              subTab === id ? "bg-brand-600 text-white" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {subTab === "form" && <PackFormEditor fields={fields} />}
      {subTab === "json" && (
        <Suspense fallback={<p className="text-xs text-gray-500">Loading JSON editor…</p>}>
          <JsonTab />
        </Suspense>
      )}
      {subTab === "preview" && (
        <div className="space-y-3">
          <ValidatePanel />
          <DryRunPanel />
        </div>
      )}

      <div className="flex flex-wrap gap-2 items-center pt-2 border-t border-surface-800">
        <button
          type="button"
          disabled={busy || liveLocked || !draft.file}
          onClick={() => void saveInPlace()}
          className="text-xs px-3 py-1.5 rounded bg-brand-700 hover:bg-brand-600 disabled:opacity-40 text-white focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          Save
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void saveAsNewDraft()}
          className="text-xs px-3 py-1.5 rounded bg-surface-700 hover:bg-surface-600 disabled:opacity-40 text-gray-100 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          Save as new Observe draft
        </button>
        {dirty && <span className="text-[10px] text-amber-400/80">Unsaved changes</span>}
        {message && <span className="text-xs text-emerald-400">{message}</span>}
        {error && (
          <span role="alert" className="text-xs text-red-400">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
