import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { cases, type SarIntentDetailResponse } from "../api/client";
import { SarApproveForFilingControls } from "../components/SarApproveForFilingControls";
import { SarInvestigativeNotesEditor } from "../components/SarInvestigativeNotesEditor";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

export default function SarIntentDetailPage() {
  const { caseId, intentId } = useParams<{ caseId: string; intentId: string }>();
  const [searchParams] = useSearchParams();
  const { tenantId: workspaceTenantId } = useTenantEnvironment();
  const tenantId = (searchParams.get("tenant_id")?.trim() || workspaceTenantId || "demo").trim();

  const [detail, setDetail] = useState<SarIntentDetailResponse | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [draftHtml, setDraftHtml] = useState<string>("");
  const [editorSeed, setEditorSeed] = useState(0);

  const locked = detail?.notes_editor_locked === true;

  const load = useCallback(async () => {
    if (!caseId || !intentId) return;
    setLoadErr(null);
    try {
      const d = await cases.getSarIntentDetail(caseId, tenantId, intentId);
      setDetail(d);
      setDraftHtml(d.investigative_notes_html ?? "");
      setEditorSeed((x) => x + 1);
    } catch (e) {
      setDetail(null);
      setLoadErr(toUserFacingError(e, { subject: "SAR intent detail", action: "load SAR intent workspace" }));
    }
  }, [caseId, intentId, tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const shaDisplay = detail?.fincen_submission_sha256_hex ?? null;

  const canSave = useMemo(() => {
    if (!detail || locked || saving) return false;
    return (draftHtml || "") !== (detail.investigative_notes_html || "");
  }, [detail, draftHtml, locked, saving]);

  const handleSave = async () => {
    if (!caseId || !intentId || !detail || locked) return;
    setSaving(true);
    setSaveErr(null);
    try {
      const out = await cases.patchSarIntentInvestigativeNotes(caseId, tenantId, intentId, { notes_html: draftHtml });
      setDetail((prev) =>
        prev
          ? {
              ...prev,
              investigative_notes_html: out.investigative_notes_html,
              notes_editor_locked: out.notes_editor_locked,
            }
          : prev,
      );
      setDraftHtml(out.investigative_notes_html ?? "");
      setEditorSeed((x) => x + 1);
    } catch (e) {
      setSaveErr(toUserFacingError(e, { subject: "SAR notes", action: "save investigative notes" }));
    } finally {
      setSaving(false);
    }
  };

  if (!caseId || !intentId) {
    return (
      <div className="max-w-3xl mx-auto p-6 text-sm text-gray-400">
        Missing case or intent id.
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <PageTitle module="cases">SAR intent workspace</PageTitle>
          <p className="text-sm text-gray-500 mt-1">
            <Link to={`/cases/${caseId}?tenant_id=${encodeURIComponent(tenantId)}`} className="text-sky-400/90 hover:underline">
              Back to case
            </Link>
            <span className="mx-2 text-gray-600">·</span>
            <span className="font-mono text-xs text-gray-400">intent {intentId}</span>
          </p>
        </div>
        {detail ? (
          <div className="text-right text-xs text-gray-500 space-y-0.5">
            <div>
              Status: <span className="font-semibold text-gray-300">{detail.status}</span>
            </div>
            {detail.notes_editor_locked ? (
              <div className="text-amber-300/90 font-medium">Uploaded (locked)</div>
            ) : null}
          </div>
        ) : null}
      </div>

      {loadErr ? (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200/90 space-y-1">
          <p>{loadErr}</p>
          <SupportIdHint
            message={loadErr}
            className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
          />
        </div>
      ) : null}

      {saveErr ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200/90 space-y-1">
          <p>{saveErr}</p>
        </div>
      ) : null}

      {detail ? (
        <SarApproveForFilingControls
          caseId={caseId}
          tenantId={tenantId}
          intentId={intentId}
          status={detail.status}
          onFiled={load}
        />
      ) : null}

      {detail && shaDisplay ? (
        <section className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-4 space-y-2" aria-labelledby="fincen-sha-heading">
          <h2 id="fincen-sha-heading" className="text-sm font-semibold text-emerald-200/95">
            FinCEN submission digest (SHA-256)
          </h2>
          <p className="text-xs text-gray-500">
            Hex digest of the on-the-wire batch bytes produced for this intent (same package as SFTP upload). Immutable while the SAR remains
            Uploaded.
          </p>
          <div className="font-mono text-xs break-all text-emerald-100/90 bg-surface-950/80 border border-emerald-500/20 rounded-lg px-3 py-2 select-all">
            {shaDisplay}
          </div>
        </section>
      ) : null}

      {detail && locked && !shaDisplay ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200/90">
          Uploaded state is locked, but no FinCEN artifact digest is available (missing SAR artifact or package build failed).
        </div>
      ) : null}

      <section className="space-y-2" aria-labelledby="sar-notes-heading">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="sar-notes-heading" className="text-sm font-semibold text-gray-200">
            Investigative notes
          </h2>
          {detail && !locked ? (
            <button
              type="button"
              disabled={!canSave}
              onClick={() => void handleSave()}
              className="rounded-lg border border-brand-500/40 bg-brand-600/20 px-3 py-1.5 text-sm text-brand-100 hover:bg-brand-600/30 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {saving ? "Saving…" : "Save notes"}
            </button>
          ) : null}
        </div>
        {detail ? (
          <SarInvestigativeNotesEditor
            key={`${intentId}-${editorSeed}`}
            initialHtml={detail.investigative_notes_html ?? ""}
            locked={locked}
            onHtmlChange={locked ? undefined : setDraftHtml}
          />
        ) : (
          <div className="min-h-[220px] rounded-lg border border-surface-600 bg-surface-950/40 animate-pulse" />
        )}
      </section>
    </div>
  );
}
