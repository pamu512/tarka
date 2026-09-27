import { lazy, Suspense, useState } from "react";
import type { EditorProps } from "@monaco-editor/react";
import { usePackDraftStore } from "../store/packDraftStore";

const MonacoEditor = lazy(() =>
  import("@monaco-editor/react").then((m) => ({ default: m.Editor })),
);

export default function JsonTab() {
  const jsonText = usePackDraftStore((s) => s.jsonText);
  const setJsonText = usePackDraftStore((s) => s.setJsonText);
  const applyJsonText = usePackDraftStore((s) => s.applyJsonText);
  const [err, setErr] = useState<string | null>(null);

  const onApply = () => {
    const r = applyJsonText();
    if (!r.ok) setErr(r.error);
    else setErr(null);
  };

  const editorProps: EditorProps = {
    height: "320px",
    defaultLanguage: "json",
    theme: "vs-dark",
    value: jsonText,
    onChange: (v) => setJsonText(v ?? ""),
    options: {
      minimap: { enabled: false },
      fontSize: 12,
      scrollBeyondLastLine: false,
    },
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm text-gray-300">JSON (same document)</h3>
        <button
          type="button"
          onClick={onApply}
          className="text-xs px-3 py-1.5 rounded bg-brand-700 hover:bg-brand-600 text-white focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          Apply JSON
        </button>
      </div>
      <Suspense fallback={<p className="text-xs text-gray-500">Loading editor…</p>}>
        <MonacoEditor {...editorProps} />
      </Suspense>
      {err && (
        <p role="alert" className="text-xs text-red-400">
          {err}
        </p>
      )}
    </div>
  );
}
