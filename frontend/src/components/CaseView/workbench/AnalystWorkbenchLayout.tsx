import type { ReactNode } from "react";
import { CASE_WORKBENCH_TABS, type CaseWorkbenchTab } from "../../../workbench/workbenchContract";
import { useCaseWorkbench } from "../../../context/CaseWorkbenchContext";
import { BenchmarkDriftTiles } from "./panels/BenchmarkDriftTiles";
import { CounterTransparencyStrip } from "./panels/CounterTransparencyStrip";
import { HilOverridePanel } from "./panels/HilOverridePanel";
import { PathReasoningPanel } from "./panels/PathReasoningPanel";
import { CopilotWorkbenchRail } from "./CopilotWorkbenchRail";
import { WorkbenchPinsRail } from "./WorkbenchPinsRail";

type AnalystWorkbenchLayoutProps = {
  header: ReactNode;
  body: ReactNode;
  timeline: ReactNode;
  audit: ReactNode;
  graph: ReactNode;
  bridgeConfirm?: ReactNode;
  knowledgeGraphRail?: ReactNode;
};

/**
 * Q2-E01 workbench composition: header · body · audit/graph tabs · snap-in panels · copilot rail · pins.
 */
export function AnalystWorkbenchLayout({ header, body, timeline, audit, graph, bridgeConfirm, knowledgeGraphRail }: AnalystWorkbenchLayoutProps) {
  const { activeTab, setActiveTab, isPanelOpen } = useCaseWorkbench();

  return (
    <>
      {bridgeConfirm}
      <div
        className="flex min-h-0 w-full flex-col xl:flex-row xl:items-stretch xl:min-h-[calc(100vh-10rem)]"
        data-workbench-version="1"
      >
        <div className="min-w-0 flex-1 space-y-6 animate-fade-in p-6">
          {isPanelOpen("pins") ? <WorkbenchPinsRail /> : null}
          {isPanelOpen("header") ? header : null}
          {isPanelOpen("benchmark_drift") ? <BenchmarkDriftTiles /> : null}
          <CounterTransparencyStrip />
          {isPanelOpen("path_reasoning") ? <PathReasoningPanel /> : null}
          {isPanelOpen("hil_overrides") ? <HilOverridePanel /> : null}
          {body}
          <WorkbenchTabBar activeTab={activeTab} onTabChange={setActiveTab} />
          {activeTab === "timeline" ? (
            <div role="tabpanel" id="case-panel-timeline" aria-labelledby="case-tab-timeline">
              {timeline}
            </div>
          ) : null}
          {activeTab === "audit" && isPanelOpen("audit") ? (
            <div role="tabpanel" id="case-panel-audit" aria-labelledby="case-tab-audit">
              {audit}
            </div>
          ) : null}
          {activeTab === "graph" && isPanelOpen("graph") ? (
            <div role="tabpanel" id="case-panel-graph" aria-labelledby="case-tab-graph">
              {graph}
            </div>
          ) : null}
        </div>
        {knowledgeGraphRail}
        <CopilotWorkbenchRail />
      </div>
    </>
  );
}

function WorkbenchTabBar({
  activeTab,
  onTabChange,
}: {
  activeTab: CaseWorkbenchTab;
  onTabChange: (tab: CaseWorkbenchTab) => void;
}) {
  return (
    <div className="border-b border-surface-700" role="tablist" aria-label="Case views">
      <div className="flex gap-1 sm:gap-6 flex-wrap">
        {CASE_WORKBENCH_TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            id={`case-tab-${tab}`}
            onClick={() => onTabChange(tab)}
            className={`pb-3 px-1 sm:px-0 text-sm font-medium capitalize transition-colors border-b-2 ${
              activeTab === tab
                ? "text-brand-400 border-brand-400"
                : "text-gray-400 border-transparent hover:text-gray-200"
            }`}
          >
            {tab === "graph" ? "Entity Graph" : tab}
          </button>
        ))}
      </div>
    </div>
  );
}
