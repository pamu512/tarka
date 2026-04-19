import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  admin,
  integrations,
  type AdminActiveSession,
  type AdminCatalogGroup,
  type AdminPendingApproval,
  type AdminUserAccess,
  type IntegrationRequestRecord,
  type PlatformAuditEvent,
  type PlatformAuditFlag,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import type { AccessModuleId } from "../config/accessModuleCatalog";
import {
  ACCESS_POLICY_PRESETS,
  matchAccessPolicyForModules,
  presetModuleSet,
  type AccessPolicyId,
} from "../config/accessPolicyPresets";
import { safeExternalHref } from "../utils/externalLinks";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "policies", label: "Groups & policies" },
  { id: "access", label: "Module access" },
  { id: "integration_requests", label: "Integration requests" },
  { id: "sessions", label: "Active users" },
  { id: "audit", label: "Audit log" },
  { id: "approvals", label: "Approvals" },
] as const;

const DEMO_TENANT = "demo";

type TabId = (typeof TABS)[number]["id"];

const DEMO_APPROVERS = [
  { id: "u-jordan", name: "Jordan Lee" },
  { id: "u-sam", name: "Sam Rivera" },
  { id: "u-admin-demo", name: "Demo Admin" },
] as const;

function flagTone(sev: PlatformAuditFlag["severity"]) {
  switch (sev) {
    case "critical":
      return "bg-red-500/20 text-red-300 border-red-500/40";
    case "high":
      return "bg-orange-500/20 text-orange-200 border-orange-500/35";
    case "warning":
      return "bg-amber-500/20 text-amber-200 border-amber-500/35";
    default:
      return "bg-surface-700 text-gray-300 border-surface-600";
  }
}

function FlagBadge({ f }: { f: PlatformAuditFlag }) {
  const label = f.type.replace(/_/g, " ");
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border ${flagTone(f.severity)}`}
      title={f.note}
    >
      {label}
    </span>
  );
}

export default function AdminPanel() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = (searchParams.get("tab") as TabId) || "overview";
  const setTab = (id: TabId) => {
    setSearchParams(id === "overview" ? {} : { tab: id }, { replace: true });
  };

  const [overview, setOverview] = useState<Awaited<ReturnType<typeof admin.overview>> | null>(null);
  const [catalog, setCatalog] = useState<AdminCatalogGroup[]>([]);
  const [users, setUsers] = useState<AdminUserAccess[]>([]);
  const [sessions, setSessions] = useState<AdminActiveSession[]>([]);
  const [audit, setAudit] = useState<PlatformAuditEvent[]>([]);
  const [approvals, setApprovals] = useState<AdminPendingApproval[]>([]);
  const [integrationRequests, setIntegrationRequests] = useState<IntegrationRequestRecord[]>([]);
  const [flagsOnly, setFlagsOnly] = useState(false);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [draftAllowed, setDraftAllowed] = useState<Set<string>>(new Set());

  const reloadAll = useCallback(async () => {
    setLoadErr(null);
    try {
      const [ov, cat, u, s, a, ap, ir] = await Promise.all([
        admin.overview(),
        admin.catalog(),
        admin.listUsersAccess(),
        admin.sessions(),
        admin.auditLog({ flags_only: flagsOnly }),
        admin.listApprovals(),
        integrations.listRequests({ tenant_id: DEMO_TENANT }).catch(() => ({ items: [], count: 0 })),
      ]);
      setOverview(ov);
      setCatalog(cat.groups);
      setUsers(u.users);
      setSessions(s.items);
      setAudit(a.items);
      setApprovals(ap.items);
      setIntegrationRequests(ir.items);
      setSelectedUserId((prev) => prev || u.users[0]?.user_id || "");
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Failed to load admin data");
    }
  }, [flagsOnly]);

  useEffect(() => {
    void reloadAll();
  }, [reloadAll]);

  useEffect(() => {
    const u = users.find((x) => x.user_id === selectedUserId);
    if (u) setDraftAllowed(new Set(u.allowed_modules));
  }, [users, selectedUserId]);

  const groupState = useCallback(
    (g: AdminCatalogGroup) => {
      const ids = g.modules.map((m) => m.id);
      const onCount = ids.filter((id) => draftAllowed.has(id)).length;
      return { all: onCount === ids.length, some: onCount > 0 && onCount < ids.length, onCount, ids };
    },
    [draftAllowed],
  );

  const toggleGroup = (g: AdminCatalogGroup, on: boolean) => {
    setDraftAllowed((prev) => {
      const next = new Set(prev);
      for (const m of g.modules) {
        if (on) next.add(m.id);
        else next.delete(m.id);
      }
      return next;
    });
    setSaveMsg(null);
  };

  const toggleModule = (id: AccessModuleId, on: boolean) => {
    setDraftAllowed((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
    setSaveMsg(null);
  };

  const applyAccessPreset = (id: AccessPolicyId) => {
    setDraftAllowed(new Set(presetModuleSet(id)));
    setSaveMsg(null);
  };

  const saveAccess = async () => {
    if (!selectedUserId) return;
    setBusy(true);
    setSaveMsg(null);
    try {
      const res = await admin.updateUserAccess(selectedUserId, {
        allowed_modules: [...draftAllowed] as AccessModuleId[],
        requested_by: "u-admin-demo",
        requested_by_name: "Demo Admin",
      });
      if ("applied" in res && res.applied === false && "pending_approval_id" in res) {
        setSaveMsg(res.message);
        setTab("approvals");
        await reloadAll();
      } else if ("applied" in res && res.applied === true) {
        setSaveMsg("Access updated (standard change — applied immediately).");
        await reloadAll();
      } else if ("error" in res) {
        setSaveMsg(String((res as { error: string }).error));
      }
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const doApprove = async (approvalId: string, approverId: string, approverName: string) => {
    setBusy(true);
    try {
      const r = await admin.approveRequest(approvalId, { approver_id: approverId, approver_name: approverName });
      if (!r.ok) setSaveMsg(r.error === "already_voted" ? "This approver already signed." : "Approve failed");
      await reloadAll();
    } finally {
      setBusy(false);
    }
  };

  const doReject = async (approvalId: string) => {
    setBusy(true);
    try {
      await admin.rejectRequest(approvalId, { approver_id: "u-admin-demo" });
      await reloadAll();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-6xl animate-fade-in pb-16">
      <PageTitle module="admin">Admin Panel</PageTitle>
      <p className="text-sm text-gray-500 -mt-2 max-w-3xl">
        Prototype console: <strong>access policies</strong> (role templates such as admin, engineering, data science,
        risk analyst, view only), module access by functional <strong>group</strong> or <strong>module</strong>, live
        sessions, audit with <strong>auto-flags</strong>, and <strong>dual approval</strong> for high-risk or core RBAC
        changes. Wire to your IdP and admin-api when ready.
      </p>

      {loadErr && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-300">{loadErr}</div>
      )}

      <div className="flex flex-wrap gap-2 border-b border-surface-700 pb-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              tab === t.id ? "bg-brand-600/25 text-brand-300" : "text-gray-500 hover:bg-surface-800 hover:text-gray-300"
            }`}
          >
            {t.label}
            {t.id === "approvals" && approvals.filter((a) => a.status === "pending").length > 0 ? (
              <span className="ml-1.5 text-[10px] tabular-nums px-1.5 py-0.5 rounded-full bg-amber-500/90 text-black">
                {approvals.filter((a) => a.status === "pending").length}
              </span>
            ) : null}
            {t.id === "integration_requests" &&
            integrationRequests.filter((r) => r.status === "pending_approval").length > 0 ? (
              <span className="ml-1.5 text-[10px] tabular-nums px-1.5 py-0.5 rounded-full bg-cyan-500/90 text-black">
                {integrationRequests.filter((r) => r.status === "pending_approval").length}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {saveMsg && (
        <div className="rounded-lg border border-brand-500/30 bg-brand-500/10 px-4 py-2 text-sm text-brand-200">{saveMsg}</div>
      )}

      {tab === "overview" && overview && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Active sessions" value={overview.active_sessions} hint="Users online now (demo)" />
          <StatCard label="Flagged audit rows" value={overview.audit_events_flagged} hint="Events with auto-flags" />
          <StatCard label="Pending approvals" value={overview.pending_approvals} hint="Maker–checker queue" />
          <StatCard label="Users in directory" value={overview.users_configured} hint="RBAC profiles" />
        </div>
      )}

      {tab === "policies" && (
        <PoliciesTab
          users={users}
          selectedUserId={selectedUserId}
          onSelectUser={(id) => {
            setSelectedUserId(id);
            const u = users.find((x) => x.user_id === id);
            if (u) setDraftAllowed(new Set(u.allowed_modules));
            setSaveMsg(null);
          }}
          onApplyPreset={(id) => {
            applyAccessPreset(id);
            setTab("access");
            setSaveMsg(`Applied “${ACCESS_POLICY_PRESETS.find((p) => p.id === id)?.label ?? id}” — review modules and save.`);
          }}
        />
      )}

      {tab === "integration_requests" && (
        <IntegrationRequestsTab
          requests={integrationRequests}
          busy={busy}
          onReload={reloadAll}
          onMessage={setSaveMsg}
        />
      )}

      {tab === "access" && (
        <AccessTab
          catalog={catalog}
          users={users}
          selectedUserId={selectedUserId}
          onSelectUser={(id) => {
            setSelectedUserId(id);
            const u = users.find((x) => x.user_id === id);
            if (u) setDraftAllowed(new Set(u.allowed_modules));
            setSaveMsg(null);
          }}
          draftAllowed={draftAllowed}
          groupState={groupState}
          toggleGroup={toggleGroup}
          toggleModule={toggleModule}
          onApplyPreset={applyAccessPreset}
          onSave={saveAccess}
          busy={busy}
        />
      )}

      {tab === "sessions" && <SessionsTab sessions={sessions} />}

      {tab === "audit" && (
        <AuditTab
          events={audit}
          flagsOnly={flagsOnly}
          onFlagsOnly={setFlagsOnly}
          users={users}
          onFilterUser={async (userId) => {
            const { items } = await admin.auditLog({ flags_only: flagsOnly, user_id: userId || undefined });
            setAudit(items);
          }}
        />
      )}

      {tab === "approvals" && (
        <ApprovalsTab approvals={approvals} busy={busy} onApprove={doApprove} onReject={doReject} />
      )}
    </div>
  );
}

function StatCard({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className="text-3xl font-semibold text-gray-100 tabular-nums mt-1">{value}</div>
      <div className="text-[11px] text-gray-600 mt-2">{hint}</div>
    </div>
  );
}

function GroupCheckbox({
  checked,
  indeterminate,
  onChange,
  label,
}: {
  checked: boolean;
  indeterminate: boolean;
  onChange: (on: boolean) => void;
  label: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);

  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <input
        ref={ref}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="rounded border-surface-600 bg-surface-800 text-brand-500 focus:ring-brand-500/40"
      />
      <span className="text-sm font-semibold text-gray-200">{label}</span>
      <span className="text-[10px] text-gray-600 font-normal">(entire group)</span>
    </label>
  );
}

function policyBadgeForUser(u: AdminUserAccess) {
  const inferred = matchAccessPolicyForModules(u.allowed_modules);
  return inferred?.shortLabel ?? "Custom";
}

function PoliciesTab({
  users,
  selectedUserId,
  onSelectUser,
  onApplyPreset,
}: {
  users: AdminUserAccess[];
  selectedUserId: string;
  onSelectUser: (id: string) => void;
  onApplyPreset: (id: AccessPolicyId) => void;
}) {
  const selected = users.find((u) => u.user_id === selectedUserId);

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-surface-700 bg-surface-900/50 p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-200">How policies work</h3>
        <p className="text-sm text-gray-500 leading-relaxed">
          <strong className="text-gray-400">Access policies</strong> are role templates: each maps to a fixed set of
          product modules. <strong className="text-gray-400">Platform admin</strong> and{" "}
          <strong className="text-gray-400">Governance &amp; audit</strong> include the Admin Panel and permission to{" "}
          <strong className="text-gray-400">add or remove</strong> access for others (enforce in your IdP or admin-api).
          Other roles are scoped to their function — e.g. <strong className="text-gray-400">View only</strong> is
          dashboards and account surfaces only. Applying a policy loads modules into{" "}
          <strong className="text-gray-400">Module access</strong>; you still <strong className="text-gray-400">Save</strong>{" "}
          to persist (subject to dual approval for core/high-risk changes).
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-6">
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500">Apply policy to</h3>
          <ul className="rounded-xl border border-surface-700 bg-surface-900 divide-y divide-surface-700 max-h-[60vh] overflow-y-auto">
            {users.map((u) => (
              <li key={u.user_id}>
                <button
                  type="button"
                  onClick={() => onSelectUser(u.user_id)}
                  className={`w-full text-left px-3 py-2.5 text-sm transition-colors ${
                    selectedUserId === u.user_id ? "bg-brand-600/15 text-brand-300" : "text-gray-300 hover:bg-surface-800"
                  }`}
                >
                  <div className="font-medium">{u.name}</div>
                  <div className="text-[10px] text-gray-600 mt-0.5">{policyBadgeForUser(u)}</div>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            {selected ? (
              <>
                Selected: <strong className="text-gray-300">{selected.name}</strong>. Choose a policy below, then
                confirm modules on <strong className="text-gray-400">Module access</strong> and save.
              </>
            ) : (
              "Select a user on the left."
            )}
          </p>

          <div className="overflow-x-auto rounded-xl border border-surface-700">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="border-b border-surface-700 text-left text-xs text-gray-500 uppercase tracking-wide bg-surface-900">
                  <th className="px-3 py-2.5">Policy</th>
                  <th className="px-3 py-2.5">Manage others’ access</th>
                  <th className="px-3 py-2.5">Modules</th>
                  <th className="px-3 py-2.5 w-[140px]">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-800 bg-surface-900/80">
                {ACCESS_POLICY_PRESETS.map((p) => (
                  <tr key={p.id} className="text-gray-300 align-top">
                    <td className="px-3 py-3">
                      <div className="font-medium text-gray-200">{p.label}</div>
                      <div className="text-[11px] text-gray-600 mt-1 leading-snug max-w-md">{p.description}</div>
                    </td>
                    <td className="px-3 py-3">
                      {p.canManageAccess ? (
                        <span className="text-[11px] font-medium text-violet-300/95 bg-violet-500/15 border border-violet-500/30 px-2 py-1 rounded-md">
                          Yes — add / remove access
                        </span>
                      ) : (
                        <span className="text-[11px] text-gray-600">No</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-xs text-gray-500 tabular-nums">{p.moduleIds.length}</span>
                      <span className="text-gray-600 text-xs"> · </span>
                      <span className="text-[11px] text-gray-500 leading-relaxed">
                        {p.moduleIds.slice(0, 6).join(", ")}
                        {p.moduleIds.length > 6 ? "…" : ""}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <button
                        type="button"
                        disabled={!selected}
                        onClick={() => onApplyPreset(p.id)}
                        className="w-full px-2 py-1.5 rounded-lg text-xs font-medium bg-brand-600/25 text-brand-200 border border-brand-500/40 hover:bg-brand-600/35 disabled:opacity-35 disabled:cursor-not-allowed"
                      >
                        Apply
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function AccessTab({
  catalog,
  users,
  selectedUserId,
  onSelectUser,
  draftAllowed,
  groupState,
  toggleGroup,
  toggleModule,
  onApplyPreset,
  onSave,
  busy,
}: {
  catalog: AdminCatalogGroup[];
  users: AdminUserAccess[];
  selectedUserId: string;
  onSelectUser: (id: string) => void;
  draftAllowed: Set<string>;
  groupState: (g: AdminCatalogGroup) => { all: boolean; some: boolean; ids: string[] };
  toggleGroup: (g: AdminCatalogGroup, on: boolean) => void;
  toggleModule: (id: AccessModuleId, on: boolean) => void;
  onApplyPreset: (id: AccessPolicyId) => void;
  onSave: () => void;
  busy: boolean;
}) {
  const [presetPicker, setPresetPicker] = useState("");
  useEffect(() => {
    setPresetPicker("");
  }, [selectedUserId]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-6">
      <div className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500">User</h3>
        <ul className="rounded-xl border border-surface-700 bg-surface-900 divide-y divide-surface-700 max-h-[70vh] overflow-y-auto">
          {users.map((u) => (
            <li key={u.user_id}>
              <button
                type="button"
                onClick={() => onSelectUser(u.user_id)}
                className={`w-full text-left px-3 py-2.5 text-sm transition-colors ${
                  selectedUserId === u.user_id ? "bg-brand-600/15 text-brand-300" : "text-gray-300 hover:bg-surface-800"
                }`}
              >
                <div className="font-medium flex items-center gap-2 flex-wrap">
                  {u.name}
                  <span
                    className={`text-[9px] uppercase px-1.5 py-0.5 rounded font-semibold ${
                      u.can_manage_access
                        ? "bg-violet-500/25 text-violet-200 border border-violet-500/35"
                        : "bg-surface-700 text-gray-400 border border-surface-600"
                    }`}
                    title={u.can_manage_access ? "May manage others’ access (policy + admin module)" : "No RBAC management"}
                  >
                    {policyBadgeForUser(u)}
                  </span>
                </div>
                <div className="text-[11px] text-gray-500 truncate">{u.email}</div>
                <div className="text-[10px] text-gray-600 mt-0.5">{u.role.replace(/_/g, " ")}</div>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-surface-700 bg-surface-900/60 px-3 py-2">
          <label className="text-xs text-gray-500 shrink-0">Role preset</label>
          <select
            value={presetPicker}
            onChange={(e) => {
              const v = e.target.value as AccessPolicyId | "";
              if (!v) {
                setPresetPicker("");
                return;
              }
              onApplyPreset(v);
              setPresetPicker("");
            }}
            className="flex-1 min-w-[12rem] max-w-md bg-surface-950 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200"
          >
            <option value="">Load a policy template…</option>
            {ACCESS_POLICY_PRESETS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
                {p.canManageAccess ? " · can manage access" : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-gray-400">
            Toggle a <strong className="text-gray-200">group</strong> to grant all modules in it, then refine per
            module. Saving touches <strong className="text-gray-200">core / high-risk</strong> modules queues{" "}
            <strong className="text-gray-200">dual approval</strong> (more than one signer).
          </p>
          <button
            type="button"
            disabled={busy || !selectedUserId}
            onClick={onSave}
            className="shrink-0 px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-500 disabled:opacity-40"
          >
            {busy ? "Saving…" : "Save access"}
          </button>
        </div>

        <div className="space-y-6">
          {catalog.map((g) => {
            const { all, some } = groupState(g);
            return (
              <div key={g.id} className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-3">
                <GroupCheckbox
                  checked={all}
                  indeterminate={some}
                  onChange={(on) => toggleGroup(g, on)}
                  label={g.label}
                />
                <div className="grid sm:grid-cols-2 gap-2 pl-6">
                  {g.modules.map((m) => (
                    <label
                      key={m.id}
                      className="flex items-center justify-between gap-2 rounded-lg border border-surface-700/80 bg-surface-950/50 px-3 py-2 cursor-pointer"
                    >
                      <span className="flex items-center gap-2 min-w-0">
                        <input
                          type="checkbox"
                          checked={draftAllowed.has(m.id)}
                          onChange={(e) => toggleModule(m.id, e.target.checked)}
                          className="rounded border-surface-600 bg-surface-800 text-brand-500 shrink-0"
                        />
                        <span className="text-sm text-gray-300 truncate">{m.label}</span>
                      </span>
                      <span className="flex flex-col items-end gap-0.5 shrink-0">
                        {m.core && (
                          <span className="text-[9px] uppercase px-1 py-0.5 rounded bg-red-500/20 text-red-300">core</span>
                        )}
                        {!m.core && m.highRisk && (
                          <span className="text-[9px] uppercase px-1 py-0.5 rounded bg-amber-500/20 text-amber-200">
                            high risk
                          </span>
                        )}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function SessionsTab({ sessions }: { sessions: AdminActiveSession[] }) {
  return (
    <div className="rounded-xl border border-surface-700 overflow-hidden bg-surface-900">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-surface-700 text-left text-xs text-gray-500 uppercase tracking-wide">
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Route</th>
              <th className="px-4 py-3">IP</th>
              <th className="px-4 py-3 text-right">Clicks / 5m</th>
              <th className="px-4 py-3 text-right">Entities / 1h</th>
              <th className="px-4 py-3 text-right">Avg dwell (s)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-700">
            {sessions.map((s) => (
              <tr key={s.session_id} className="text-gray-300">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-200">{s.user_name}</div>
                  <div className="text-[11px] text-gray-500">{s.email}</div>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-brand-300/90">{s.current_route}</td>
                <td className="px-4 py-3 font-mono text-xs">{s.ip}</td>
                <td className="px-4 py-3 text-right tabular-nums">{s.clicks_last_5m}</td>
                <td className="px-4 py-3 text-right tabular-nums">{s.entities_touched_1h}</td>
                <td className="px-4 py-3 text-right tabular-nums">{s.avg_dwell_seconds}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-600 px-4 py-2 border-t border-surface-700">
        Session telemetry is illustrative; connect streaming activity + SIEM for production.
      </p>
    </div>
  );
}

function IntegrationRequestsTab({
  requests,
  busy,
  onReload,
  onMessage,
}: {
  requests: IntegrationRequestRecord[];
  busy: boolean;
  onReload: () => Promise<void>;
  onMessage: (msg: string | null) => void;
}) {
  const pending = requests.filter((r) => r.status === "pending_approval");
  const settled = requests.filter((r) => r.status !== "pending_approval");

  const doApprove = async (requestId: string, approverId: string, approverName: string) => {
    try {
      const res = await integrations.approveRequest(requestId, { approver_id: approverId, approver_name: approverName });
      if (!res.ok) {
        onMessage(String(res.error ?? "Approve failed"));
        await onReload();
        return;
      }
      if (res.github_issue_url) {
        window.open(res.github_issue_url, "_blank", "noopener,noreferrer");
      }
      onMessage(
        res.already_approved
          ? "Already approved — GitHub link is on the request record."
          : "Approved — opened prefilled GitHub issue for developers.",
      );
      await onReload();
    } catch (e) {
      onMessage(e instanceof Error ? e.message : "Approve failed");
      await onReload();
    }
  };

  const doReject = async (requestId: string) => {
    try {
      await integrations.rejectRequest(requestId, { reason: "Declined by administrator" });
      onMessage("Request rejected.");
      await onReload();
    } catch (e) {
      onMessage(e instanceof Error ? e.message : "Reject failed");
      await onReload();
    }
  };

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-500 max-w-3xl">
        When someone requests a <strong className="text-gray-400">new integration</strong> from the Integrations page,
        it appears here. <strong className="text-gray-400">Approve</strong> to generate the prefilled GitHub new-issue URL
        and send work to engineering; <strong className="text-gray-400">Reject</strong> to close the request without a
        ticket.
      </p>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-300">Pending approval</h3>
        {pending.length === 0 ? (
          <p className="text-sm text-gray-600">No integration requests awaiting approval.</p>
        ) : (
          <ul className="space-y-4">
            {pending.map((r) => (
              <li key={r.id} className="rounded-xl border border-cyan-500/25 bg-surface-900 p-4 space-y-3">
                <div className="flex flex-wrap justify-between gap-2">
                  <div>
                    <div className="text-sm font-medium text-gray-100">{r.requested_name}</div>
                    <div className="text-xs text-gray-500 mt-1">
                      {r.category} · tenant <span className="text-gray-400">{r.tenant_id}</span>
                    </div>
                    <div className="text-xs text-gray-400 mt-2 max-w-xl">{r.use_case}</div>
                    <div className="text-[11px] text-gray-600 mt-2">
                      Requested <span className="text-gray-500">{r.requested_at ? new Date(r.requested_at).toLocaleString() : "—"}</span>
                      {r.github_username ? (
                        <>
                          {" "}
                          · GitHub <span className="text-gray-500">@{r.github_username}</span>
                        </>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {DEMO_APPROVERS.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        disabled={busy}
                        onClick={() => void doApprove(r.id, p.id, p.name)}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-brand-600/30 text-brand-200 border border-brand-500/40 hover:bg-brand-600/40 disabled:opacity-35"
                      >
                        Approve as {p.name.split(" ")[0]}
                      </button>
                    ))}
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void doReject(r.id)}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-700 text-gray-300 border border-surface-600 hover:bg-surface-600 disabled:opacity-35"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {settled.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-500">Processed</h3>
          <ul className="text-sm text-gray-500 space-y-2">
            {settled.map((r) => (
              <li key={r.id} className="rounded-lg border border-surface-800 bg-surface-900/60 px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded ${
                      r.status === "approved" ? "bg-emerald-500/20 text-emerald-300" : "bg-red-500/15 text-red-300"
                    }`}
                  >
                    {r.status}
                  </span>
                  <span className="text-gray-300">{r.requested_name}</span>
                </div>
                {r.status === "approved" && (
                  (() => {
                    const safeIssueHref = safeExternalHref(r.github_issue_url);
                    return safeIssueHref ? (
                      <a
                        href={safeIssueHref}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-brand-400 hover:text-brand-300 mt-1 inline-block break-all"
                      >
                        Open GitHub issue draft
                      </a>
                    ) : (
                      <span className="text-[11px] text-gray-500 mt-1 inline-block">
                        Issue draft URL unavailable
                      </span>
                    );
                  })()
                )}
                {r.status === "rejected" && r.rejection_reason ? (
                  <div className="text-[11px] text-gray-600 mt-1">{r.rejection_reason}</div>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function AuditTab({
  events,
  flagsOnly,
  onFlagsOnly,
  users,
  onFilterUser,
}: {
  events: PlatformAuditEvent[];
  flagsOnly: boolean;
  onFlagsOnly: (v: boolean) => void;
  users: AdminUserAccess[];
  onFilterUser: (userId: string) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 items-center">
        <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={flagsOnly}
            onChange={(e) => onFlagsOnly(e.target.checked)}
            className="rounded border-surface-600 bg-surface-800 text-brand-500"
          />
          Flagged only
        </label>
        <select
          className="bg-surface-900 border border-surface-600 rounded-lg px-3 py-1.5 text-sm text-gray-300"
          onChange={(e) => void onFilterUser(e.target.value)}
          defaultValue=""
        >
          <option value="">All users</option>
          {users.map((u) => (
            <option key={u.user_id} value={u.user_id}>
              {u.name}
            </option>
          ))}
        </select>
      </div>
      <div className="text-[11px] text-gray-600 space-y-1">
        <p>
          <strong className="text-gray-500">Auto-flags</strong> include high click rate, suspiciously low AHT on case
          actions, bulk entity access, edits to tier-1 rules, core integration/KMS changes, and blocked guardrail /
          hardening bypass attempts.
        </p>
      </div>
      <div className="rounded-xl border border-surface-700 overflow-hidden bg-surface-900 max-h-[min(560px,70vh)] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface-900 z-10">
            <tr className="border-b border-surface-700 text-left text-xs text-gray-500 uppercase tracking-wide">
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">User</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Resource</th>
              <th className="px-3 py-2">Detail</th>
              <th className="px-3 py-2">Flags</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-800">
            {events.map((e) => (
              <tr key={e.id} className="text-gray-300 align-top">
                <td className="px-3 py-2 whitespace-nowrap text-xs text-gray-500 font-mono">
                  {new Date(e.ts).toLocaleString()}
                </td>
                <td className="px-3 py-2 text-xs">{e.user_name}</td>
                <td className="px-3 py-2 text-xs uppercase text-gray-400">{e.action}</td>
                <td className="px-3 py-2 text-xs font-mono text-brand-300/80">{e.resource}</td>
                <td className="px-3 py-2 text-xs text-gray-400 max-w-[200px]">{e.detail}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {e.flags.length === 0 ? (
                      <span className="text-gray-600 text-xs">—</span>
                    ) : (
                      e.flags.map((f) => <FlagBadge key={`${e.id}-${f.type}`} f={f} />)
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ApprovalsTab({
  approvals,
  busy,
  onApprove,
  onReject,
}: {
  approvals: AdminPendingApproval[];
  busy: boolean;
  onApprove: (id: string, approverId: string, approverName: string) => void;
  onReject: (id: string) => void;
}) {
  const pending = approvals.filter((a) => a.status === "pending");
  const done = approvals.filter((a) => a.status !== "pending");

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-300">Pending — requires {">"}1 approver</h3>
        {pending.length === 0 ? (
          <p className="text-sm text-gray-600">No items in queue.</p>
        ) : (
          <ul className="space-y-4">
            {pending.map((a) => (
              <li key={a.id} className="rounded-xl border border-amber-500/25 bg-surface-900 p-4 space-y-3">
                <div className="flex flex-wrap justify-between gap-2">
                  <div>
                    <div className="text-xs text-gray-500">{new Date(a.requested_at).toLocaleString()}</div>
                    <div className="text-sm text-gray-200 font-medium">{a.summary}</div>
                    <div className="text-xs text-gray-500 mt-1">
                      Target: <span className="text-gray-300">{a.target_user_name}</span> · Risk:{" "}
                      <span className="text-amber-300/90">{a.risk_tier}</span> · Required votes:{" "}
                      <span className="tabular-nums">{a.required_approvals}</span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {DEMO_APPROVERS.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        disabled={busy || a.votes.some((v) => v.user_id === p.id)}
                        onClick={() => onApprove(a.id, p.id, p.name)}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-brand-600/30 text-brand-200 border border-brand-500/40 hover:bg-brand-600/40 disabled:opacity-35"
                      >
                        Approve as {p.name.split(" ")[0]}
                      </button>
                    ))}
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onReject(a.id)}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-700 text-gray-300 border border-surface-600 hover:bg-surface-600"
                    >
                      Reject
                    </button>
                  </div>
                </div>
                <div className="text-[11px] text-gray-500">
                  Votes:{" "}
                  {a.votes.length === 0 ? (
                    "none yet"
                  ) : (
                    <span className="text-gray-400">
                      {a.votes.map((v) => `${v.user_name} @ ${new Date(v.at).toLocaleTimeString()}`).join(" · ")}
                    </span>
                  )}
                </div>
                <div className="grid sm:grid-cols-2 gap-2 text-[11px] font-mono">
                  <div className="rounded-lg bg-surface-950/80 p-2 border border-surface-700">
                    <div className="text-gray-500 mb-1">Before</div>
                    <div className="text-gray-400 break-all">{(a.previous_allowed_modules ?? []).join(", ") || "—"}</div>
                  </div>
                  <div className="rounded-lg bg-surface-950/80 p-2 border border-surface-700">
                    <div className="text-gray-500 mb-1">After (proposed)</div>
                    <div className="text-gray-300 break-all">{(a.proposed_allowed_modules ?? []).join(", ") || "—"}</div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {done.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-500">Completed</h3>
          <ul className="text-sm text-gray-500 space-y-1">
            {done.map((a) => (
              <li key={a.id} className="flex gap-2">
                <span className="text-gray-600">{a.status}</span>
                <span className="text-gray-400 truncate">{a.summary}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
